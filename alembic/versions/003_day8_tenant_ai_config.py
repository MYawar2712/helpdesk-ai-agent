"""Day 8: tenant AI configuration and knowledge chunks.

Extends ``ai_configurations`` from one row per tenant to one row per
``(tenant_id, agent_type)`` pair, and adds the relational chunk table that backs
tenant-scoped retrieval. Existing rows are preserved as ``GLOBAL`` configs.

``ai_configurations`` is rebuilt with create/copy/drop/rename rather than
``ALTER`` because the Day 1 table carries an *unnamed* unique constraint on
``tenant_id`` whose database-side name differs between SQLite and PostgreSQL and
so cannot be dropped reliably by name.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_day8_tenant_ai_config"
down_revision: str | None = "002_day6_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_configurations"
_STAGING = "ai_configurations_day8_staging"

_BASE_COLUMNS = [
    "id",
    "tenant_id",
    "global_instructions",
    "tone",
    "escalation_rules",
    "business_rules",
    "updated_at",
]
_DAY8_COLUMNS = [
    "id",
    "tenant_id",
    "agent_type",
    "instructions",
    "global_instructions",
    "tone",
    "escalation_rules",
    "business_rules",
    "allowed_tools",
    "is_active",
    "created_at",
    "updated_at",
]


def _column(name: str, *, day8: bool) -> sa.Column:
    """Return the column definition used by the rebuilt table."""

    match name:
        case "id" | "tenant_id":
            return sa.Column(name, sa.String(length=36), nullable=False)
        case "agent_type":
            return sa.Column(
                name, sa.String(length=50), nullable=False, server_default="GLOBAL"
            )
        case "instructions" | "global_instructions" | "content":
            return sa.Column(name, sa.Text(), nullable=True)
        case "tone":
            return sa.Column(name, sa.String(length=255), nullable=True)
        case "escalation_rules" | "business_rules" | "allowed_tools":
            return sa.Column(name, sa.JSON(), nullable=True)
        case "is_active":
            return sa.Column(
                name, sa.Boolean(), nullable=False, server_default=sa.true()
            )
        case "created_at" | "updated_at":
            return sa.Column(
                name,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
    raise ValueError(f"unsupported column: {name}")


def _staging_table(*, day8: bool) -> sa.Table:
    columns = _DAY8_COLUMNS if day8 else _BASE_COLUMNS
    metadata = sa.MetaData()
    # The referenced table must be present in the same metadata for the foreign
    # key to render; a minimal definition is enough.
    sa.Table("tenants", metadata, sa.Column("id", sa.String(length=36)))
    constraints = [
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    ]
    if day8:
        # Created inline: SQLite cannot add a unique constraint via ALTER.
        constraints.append(
            sa.UniqueConstraint(
                "tenant_id", "agent_type", name="uq_ai_config_tenant_agent"
            )
        )
    return sa.Table(
        _STAGING,
        metadata,
        *[_column(name, day8=day8) for name in columns],
        *constraints,
    )


def _rebuild_ai_configurations(*, day8: bool) -> None:
    """Recreate ``ai_configurations`` with the requested shape, keeping rows."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return

    existing = {item["name"] for item in inspector.get_columns(_TABLE)}
    if day8 and "agent_type" in existing:
        return  # already on the Day 8 shape

    target = _staging_table(day8=day8)
    target.create(bind, checkfirst=True)

    # Columns that did not exist in Day 1 are filled with a safe default.
    default_expressions = {
        "agent_type": sa.literal("GLOBAL", type_=sa.String(50)),
        "instructions": sa.literal(None, type_=sa.Text()),
        "allowed_tools": sa.literal(None, type_=sa.JSON()),
        "is_active": sa.literal(True, type_=sa.Boolean()),
        "created_at": sa.func.now(),
    }
    names = _DAY8_COLUMNS if day8 else _BASE_COLUMNS
    destination = [
        name for name in names if name in existing or name in default_expressions
    ]
    source: list = [
        sa.column(name) if name in existing else default_expressions[name]
        for name in destination
    ]

    # A light-weight table clause for the table being copied out of.
    legacy = sa.table(_TABLE, *[sa.column(name) for name in destination])

    bind.execute(
        target.insert().from_select(destination, sa.select(*source).select_from(legacy))
    )

    for index in _ai_config_indexes(inspector):
        op.drop_index(index, table_name=_TABLE)
    op.drop_table(_TABLE)
    op.rename_table(_STAGING, _TABLE)

    if day8:
        op.create_index(f"ix_{_TABLE}_tenant_id", _TABLE, ["tenant_id"])
        op.create_index(f"ix_{_TABLE}_agent_type", _TABLE, ["agent_type"])
    else:
        op.create_index(f"ix_{_TABLE}_tenant_id", _TABLE, ["tenant_id"], unique=True)


def _ai_config_indexes(inspector: sa.Inspector) -> list[str]:
    """Return index names currently defined on ``ai_configurations``."""

    return [index["name"] for index in inspector.get_indexes(_TABLE)]


def upgrade() -> None:
    """Add per-agent configuration columns and the knowledge chunk table."""

    _rebuild_ai_configurations(day8=True)

    if not sa.inspect(op.get_bind()).has_table("knowledge_chunks"):
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("chunk_metadata", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "document_id", "chunk_index", name="uq_knowledge_chunk_doc_index"
            ),
        )
        op.create_index(
            "ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"]
        )
        op.create_index(
            "ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"]
        )


def downgrade() -> None:
    """Restore the single-config-per-tenant shape and drop the chunk table."""

    if sa.inspect(op.get_bind()).has_table("knowledge_chunks"):
        op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
        op.drop_index("ix_knowledge_chunks_tenant_id", table_name="knowledge_chunks")
        op.drop_table("knowledge_chunks")

    _rebuild_ai_configurations(day8=False)
