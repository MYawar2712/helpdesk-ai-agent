"""Day 9: human-in-the-loop approval requests.

Adds the ``approval_requests`` table backing the HITL workflow. No existing
conversation, message, or audit data is modified.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_day9_approvals"
down_revision: str | None = "003_day8_tenant_ai_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the approval_requests table and its indexes."""

    if sa.inspect(op.get_bind()).has_table("approval_requests"):
        return

    metadata = sa.MetaData()
    # Referenced tables must be present in the same metadata for the foreign
    # keys to render; minimal definitions are sufficient.
    sa.Table("tenants", metadata, sa.Column("id", sa.String(length=36)))
    sa.Table("users", metadata, sa.Column("id", sa.String(length=36)))

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("ticket_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column("agent_type", sa.String(length=50), nullable=False),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "risk_level", sa.String(length=20), nullable=False, server_default="LOW"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="PENDING"
        ),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("execution_result", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    for column in (
        "tenant_id",
        "conversation_id",
        "ticket_id",
        "agent_type",
        "action_type",
        "status",
        "expires_at",
    ):
        op.create_index(f"ix_approval_requests_{column}", "approval_requests", [column])


def downgrade() -> None:
    """Drop the approval_requests table."""

    for column in (
        "expires_at",
        "status",
        "action_type",
        "agent_type",
        "ticket_id",
        "conversation_id",
        "tenant_id",
    ):
        op.drop_index(f"ix_approval_requests_{column}", table_name="approval_requests")
    op.drop_table("approval_requests")
