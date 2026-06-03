"""Add rag_debug_traces table (RAG debug trace).

One row per traced chat request, keyed by the request correlation_id.
Self-contained full pipeline trace for answer debugging. Independent of
llm_generation_log.

Revision ID: 024
Revises: 023
Create Date: 2026-06-02
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "024"
down_revision: str | None = "023"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_debug_traces",
        sa.Column("trace_id", UUID(as_uuid=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("total_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("trace", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("trace_id"),
    )
    op.create_index(
        "ix_rag_debug_traces_ws_created",
        "rag_debug_traces",
        ["workspace_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_debug_traces_ws_created", table_name="rag_debug_traces")
    op.drop_table("rag_debug_traces")
