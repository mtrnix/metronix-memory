"""Add agents and agent_config_versions tables for WS4.

Revision ID: 017
Revises: 016
Create Date: 2026-04-21
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="stopped"),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column(
            "capabilities",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "tools",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "memory_bindings",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "budget",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "config_version",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "current_config",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.Text, nullable=False, server_default=""),
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
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'stopped', 'archived')",
            name="ck_agents_status",
        ),
    )
    op.create_index("ix_agents_workspace", "agents", ["workspace_id"])
    op.create_index(
        "ix_agents_workspace_status",
        "agents",
        ["workspace_id", "status"],
    )
    # Partial unique index — archived agents do not occupy the name slot,
    # so a fresh registration with the same name after soft-delete succeeds.
    op.create_index(
        "uq_agents_workspace_name",
        "agents",
        ["workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("status <> 'archived'"),
    )

    op.create_table(
        "agent_config_versions",
        sa.Column(
            "agent_id",
            sa.Text,
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "config",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("changed_by", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("agent_id", "version"),
    )


def downgrade() -> None:
    op.drop_table("agent_config_versions")
    op.drop_table("agents")
