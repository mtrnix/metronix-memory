"""Add graph-extraction failure tracking to raw_documents.

When LLM-based graph extraction (NER) exhausts its retries for a document, the
document was previously left ``graph_synced=false`` and retried forever by the
sweeper — a document that structurally never fits the timeout becomes a
CPU-burning loop that can stall the rest of the backlog.

This migration adds an explicit terminal failure state so such a document is
parked instead of looped:

- ``graph_failed`` — set true after extraction gives up; excluded from the
  unsynced backlog so the sweeper stops retrying it automatically.
- ``graph_error`` — the last error message, for visibility / UI.
- ``graph_failed_at`` — when it was parked.

A failed document is re-armed by clearing ``graph_failed`` (the "retry failed"
admin action), which puts it back in the unsynced backlog.

Revision ID: 027
Revises: 026
Create Date: 2026-06-30
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "raw_documents",
        sa.Column("graph_failed", sa.Boolean, nullable=False, server_default="false"),
    )
    op.add_column(
        "raw_documents",
        sa.Column("graph_error", sa.Text, nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column("graph_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Re-create the unsynced-graph partial index so it covers the sweeper's
    # query (NOT graph_synced AND NOT graph_failed) — parked failures drop out.
    op.drop_index("ix_raw_docs_graph_unsynced", table_name="raw_documents")
    op.create_index(
        "ix_raw_docs_graph_unsynced",
        "raw_documents",
        ["workspace_id"],
        postgresql_where=sa.text("NOT graph_synced AND NOT graph_failed"),
    )


def downgrade() -> None:
    op.drop_index("ix_raw_docs_graph_unsynced", table_name="raw_documents")
    op.create_index(
        "ix_raw_docs_graph_unsynced",
        "raw_documents",
        ["workspace_id"],
        postgresql_where=sa.text("NOT graph_synced"),
    )
    op.drop_column("raw_documents", "graph_failed_at")
    op.drop_column("raw_documents", "graph_error")
    op.drop_column("raw_documents", "graph_failed")
