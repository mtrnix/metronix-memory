"""Persist temporary conversation events and durable compaction ledgers.

Revision ID: 029
Revises: 028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "029"
down_revision: str | None = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compacted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conversation_events_workspace_expires_at",
        "conversation_events",
        ["workspace_id", "expires_at"],
    )
    op.create_index(
        "ix_conversation_events_uncompacted_session",
        "conversation_events",
        ["workspace_id", "agent_id", "session_id", "created_at"],
        postgresql_where=sa.text("compacted_at IS NULL"),
    )

    op.create_table(
        "session_ledgers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_hashes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "agent_id",
            "session_id",
            "generation",
            name="uq_session_ledgers_workspace_agent_session_generation",
        ),
    )


def downgrade() -> None:
    op.drop_table("session_ledgers")
    op.drop_index("ix_conversation_events_uncompacted_session", table_name="conversation_events")
    op.drop_index(
        "ix_conversation_events_workspace_expires_at", table_name="conversation_events"
    )
    op.drop_table("conversation_events")
