"""Add memory_records and memory_snapshots tables for WS1.

Revision ID: 013
Revises: 012
Create Date: 2026-04-14
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "tags",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "importance_score",
            sa.Float,
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column("ttl_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("session_id", sa.Text, nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index("ix_memory_records_workspace", "memory_records", ["workspace_id"])
    op.create_index("ix_memory_records_agent", "memory_records", ["workspace_id", "agent_id"])
    op.create_index("ix_memory_records_scope", "memory_records", ["workspace_id", "scope"])
    op.create_index(
        "ix_memory_records_ttl",
        "memory_records",
        ["workspace_id", "ttl_expires_at"],
        postgresql_where=sa.text("ttl_expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_memory_records_content_hash",
        "memory_records",
        ["workspace_id", "agent_id", "content_hash"],
    )
    op.create_index(
        "ix_memory_records_tags",
        "memory_records",
        ["tags"],
        postgresql_using="gin",
    )

    op.create_table(
        "memory_snapshots",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False, server_default=""),
        sa.Column("trigger", sa.Text, nullable=False, server_default="manual"),
        sa.Column("record_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("content_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("storage_path", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index(
        "ix_memory_snapshots_agent",
        "memory_snapshots",
        ["workspace_id", "agent_id"],
    )


def downgrade() -> None:
    op.drop_table("memory_snapshots")
    op.drop_table("memory_records")
