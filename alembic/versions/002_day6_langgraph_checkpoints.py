"""Add the official LangGraph PostgreSQL checkpoint schema.

The LangGraph PostgreSQL saver owns the checkpoint table definitions.  This
migration applies the saver's own migrations through Alembic so deployments do
not depend on application startup order.  SQLite is intentionally a no-op; the
local saver creates its separate file-backed checkpoint schema on first use.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002_day6_checkpoints"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _applied_versions(bind: sa.Connection) -> set[int]:
    """Return checkpoint migration versions already present in PostgreSQL.

    In offline (``--sql``) mode there is no live connection to inspect, so the
    full set of statements is rendered instead.
    """

    if op.get_context().as_sql:
        return set()

    try:
        inspector = sa.inspect(bind)
        if not inspector.has_table("checkpoint_migrations"):
            return set()
        return {
            int(row[0])
            for row in bind.execute(sa.text("SELECT v FROM checkpoint_migrations"))
        }
    except sa.exc.NoInspectionAvailable:
        return set()


def upgrade() -> None:
    """Create the official LangGraph checkpoint tables on PostgreSQL."""

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    from langgraph.checkpoint.postgres import PostgresSaver

    applied = _applied_versions(bind)
    context = op.get_context()
    for version, statement in enumerate(PostgresSaver.MIGRATIONS):
        if version in applied:
            continue
        if "CONCURRENTLY" in statement.upper():
            # PostgreSQL refuses CREATE INDEX CONCURRENTLY inside a transaction.
            with context.autocommit_block():
                op.execute(sa.text(statement))
        else:
            op.execute(sa.text(statement))
        op.execute(
            sa.text(
                "INSERT INTO checkpoint_migrations (v) VALUES (:version) "
                "ON CONFLICT (v) DO NOTHING"
            ).bindparams(version=version)
        )


def downgrade() -> None:
    """Remove only LangGraph checkpoint tables; business data is untouched."""

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in (
        "checkpoint_writes",
        "checkpoint_blobs",
        "checkpoints",
        "checkpoint_migrations",
    ):
        op.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
