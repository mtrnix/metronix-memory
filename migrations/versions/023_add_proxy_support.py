"""Proxy LLM support (MTRNIX-372).

- agents.is_system column (hides workspace-default chat agent from the list).
- llm_upstream_credentials table (Fernet-encrypted upstream API keys).
- agent_activity_log.correlation_id column + partial index (per-call trace).
- Data migration: one is_system=true 'system-chat' agent per workspace.
  NOTE (MTRNIX-372 review W6): this agent is GROUNDWORK for the parked OWUI
  cutover (D-5). The current A-full rag path runs with agent_id=None and does
  NOT consume it yet; it is created now so the cutover is a config-only change.
  Requires gen_random_uuid() (built into PostgreSQL >= 13; this repo runs PG16).

Revision ID: 023
Revises: 022
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "023"
down_revision: str | None = "022"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 1. agents.is_system
    op.add_column(
        "agents",
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )

    # 2. llm_upstream_credentials
    op.create_table(
        "llm_upstream_credentials",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("fernet_encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_upstream_creds_ws_provider",
        "llm_upstream_credentials",
        ["workspace_id", "provider"],
    )

    # 3. agent_activity_log.correlation_id (D8)
    op.add_column(
        "agent_activity_log",
        sa.Column("correlation_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_activity_correlation",
        "agent_activity_log",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )

    # 4. Data migration — one system-chat agent per workspace. Idempotent.
    op.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, status, model,
                capabilities, tools, memory_bindings, budget,
                config_version, current_config, is_system,
                created_by, created_at, updated_at
            )
            SELECT
                replace(gen_random_uuid()::text, '-', ''),
                w.id, 'system-chat', 'stopped', 'gpt-4o-mini',
                '["knowledge_base"]'::jsonb, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb,
                1,
                '{"upstream": {"provider": "openai", "model_name": "gpt-4o-mini", "api_key_ref": null}}'::jsonb,
                true,
                'system', NOW(), NOW()
            FROM workspaces w
            WHERE NOT EXISTS (
                SELECT 1 FROM agents a
                WHERE a.workspace_id = w.id AND a.is_system = true
            )
            """
        )
    )


def downgrade() -> None:
    # Scope to the rows THIS migration created — never touch other is_system agents.
    op.execute(
        sa.text(
            "DELETE FROM agents WHERE is_system = true "
            "AND name = 'system-chat' AND created_by = 'system'"
        )
    )
    op.drop_index("ix_activity_correlation", table_name="agent_activity_log")
    op.drop_column("agent_activity_log", "correlation_id")
    op.drop_index("ix_upstream_creds_ws_provider", table_name="llm_upstream_credentials")
    op.drop_table("llm_upstream_credentials")
    op.drop_column("agents", "is_system")
