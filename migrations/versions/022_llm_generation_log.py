"""Add llm_generation_log table and workspaces.llm_telemetry_opt_out column (MTRNIX-336).

Captures every LLM completion that flows through Metronix for later fine-tuning
dataset assembly. One row per public ``chat_completion()`` invocation.

Also adds ``llm_telemetry_opt_out`` to ``workspaces`` so per-workspace PII
opt-out can be toggled by operators without redeployment.

Note on reversibility:
    ``downgrade()`` drops the ``workspaces.llm_telemetry_opt_out`` column
    outright — no archive step. Any opt-out flags an operator set will be
    LOST on downgrade. This is acceptable for a boolean operator-intent
    flag, but document it in the operator runbook before rolling back.
    The ``llm_generation_log`` table is dropped as a whole; export the
    table to JSONL via ``scripts/export_llm_dataset.py`` first if the
    accumulated data still has value after downgrade.

Revision ID: 022
Revises: 021
Create Date: 2026-05-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "022"
down_revision: str | None = "021"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_generation_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # -- what kind of call --
        sa.Column("call_site", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        # -- request context (from ContextVar; may be NULL) --
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=False), nullable=True),
        # -- model + provider --
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        # -- the exchange --
        sa.Column("request_messages", JSONB(), nullable=False),
        sa.Column("response_content", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        # -- outcome --
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        # -- call-site-specific extras --
        sa.Column("metadata", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # Outcome coherence check:
        #   success=True  => response_content must be non-NULL
        #   success=False => error_class must be set
        sa.CheckConstraint(
            "(success AND response_content IS NOT NULL)"
            " OR (NOT success AND error_class IS NOT NULL)",
            name="chk_outcome_coherent",
        ),
    )

    op.create_index(
        "ix_llm_log_ws_created",
        "llm_generation_log",
        ["workspace_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_llm_log_call_site_created",
        "llm_generation_log",
        ["call_site", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_llm_log_correlation",
        "llm_generation_log",
        ["correlation_id"],
        postgresql_where=sa.text("correlation_id IS NOT NULL"),
    )

    op.add_column(
        "workspaces",
        sa.Column(
            "llm_telemetry_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "llm_telemetry_opt_out")
    op.drop_index("ix_llm_log_correlation", table_name="llm_generation_log")
    op.drop_index("ix_llm_log_call_site_created", table_name="llm_generation_log")
    op.drop_index("ix_llm_log_ws_created", table_name="llm_generation_log")
    op.drop_table("llm_generation_log")
