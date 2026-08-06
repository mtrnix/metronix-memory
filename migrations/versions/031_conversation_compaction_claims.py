"""Add durable exclusive claims for explicit conversation compaction.

Revision ID: 031
Revises: 030
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "031"
down_revision: str | None = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_compaction_claims",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("event_ids", postgresql.JSONB(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "agent_id",
            "session_id",
            name="uq_conversation_compaction_claims_workspace_agent_session",
        ),
    )
    op.create_index(
        "ix_conversation_compaction_claims_expires_at",
        "conversation_compaction_claims",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_compaction_claims_expires_at",
        table_name="conversation_compaction_claims",
    )
    op.drop_table("conversation_compaction_claims")
