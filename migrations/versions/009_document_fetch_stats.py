"""Add document_fetch_stats table for FinOps cost savings.

Revision ID: 009
Revises: 008
Create Date: 2026-03-20
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_fetch_stats",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.String(64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_label", sa.String(512), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False, server_default=""),
        sa.Column("fetch_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_context_words", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "fetch_date",
            sa.Date,
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "doc_label", "fetch_date", name="uq_doc_fetch_stats"
        ),
    )
    op.create_index(
        "ix_doc_fetch_stats_workspace", "document_fetch_stats", ["workspace_id"]
    )
    op.create_index(
        "ix_doc_fetch_stats_date",
        "document_fetch_stats",
        ["workspace_id", "fetch_date"],
    )
    op.execute(
        "CREATE INDEX ix_doc_fetch_stats_lookup "
        "ON document_fetch_stats(workspace_id, fetch_date, fetch_count DESC)"
    )


def downgrade() -> None:
    op.drop_table("document_fetch_stats")
