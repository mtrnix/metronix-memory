"""Add observability tables: query_traces, sync_logs, error_logs.

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 00:00:02.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Query traces (JSONB for flexible trace data) ---
    op.create_table(
        "query_traces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("trace", JSONB, nullable=False),
        sa.Column("total_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_query_traces_workspace", "query_traces", ["workspace_id"])
    op.create_index("ix_query_traces_created", "query_traces", ["created_at"])

    # --- Sync logs (one per sync run per connection) ---
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", sa.String(64), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("documents_fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_new", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", JSONB, nullable=False, server_default="[]"),
        sa.Column("duration_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sync_logs_workspace", "sync_logs", ["workspace_id"])
    op.create_index("ix_sync_logs_connection", "sync_logs", ["connection_id"])

    # --- Error logs (structured error tracking) ---
    op.create_table(
        "error_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=True),
        sa.Column("component", sa.String(128), nullable=False),
        sa.Column("error_type", sa.String(128), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_error_logs_component", "error_logs", ["component"])
    op.create_index("ix_error_logs_created", "error_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_error_logs_created", table_name="error_logs")
    op.drop_index("ix_error_logs_component", table_name="error_logs")
    op.drop_table("error_logs")
    op.drop_index("ix_sync_logs_connection", table_name="sync_logs")
    op.drop_index("ix_sync_logs_workspace", table_name="sync_logs")
    op.drop_table("sync_logs")
    op.drop_index("ix_query_traces_created", table_name="query_traces")
    op.drop_index("ix_query_traces_workspace", table_name="query_traces")
    op.drop_table("query_traces")
