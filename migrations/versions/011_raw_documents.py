"""Add raw_documents table for document store layer.

Revision ID: 011
Revises: 010
Create Date: 2026-03-27
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop old table if it exists with wrong schema.
    # Safe: raw_documents are re-fetched from connectors on next sync.
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "raw_documents"):
        op.drop_table("raw_documents")

    op.create_table(
        "raw_documents",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("connector_type", sa.Text, nullable=False),
        sa.Column("connection_id", sa.Text, nullable=True),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("url", sa.Text, nullable=False, server_default=""),
        sa.Column("author", sa.Text, nullable=False, server_default=""),
        sa.Column("content_hash", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_role",
            sa.Text,
            nullable=False,
            server_default="knowledge_base",
        ),
        sa.Column("qdrant_synced", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("graph_synced", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("qdrant_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("graph_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
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
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "workspace_id",
            "connector_type",
            "source_id",
            name="uq_raw_docs_ws_connector_source",
        ),
    )

    op.create_index(
        "ix_raw_docs_workspace",
        "raw_documents",
        ["workspace_id"],
    )
    op.create_index(
        "ix_raw_docs_qdrant_unsynced",
        "raw_documents",
        ["workspace_id"],
        postgresql_where=sa.text("NOT qdrant_synced"),
    )
    op.create_index(
        "ix_raw_docs_graph_unsynced",
        "raw_documents",
        ["workspace_id"],
        postgresql_where=sa.text("NOT graph_synced"),
    )


def downgrade() -> None:
    op.drop_table("raw_documents")
