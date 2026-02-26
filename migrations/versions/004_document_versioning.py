"""Add document_versions table for temporal tracking.

Revision ID: 004
Revises: 003
Create Date: 2026-02-22 10:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create document_versions table for temporal document tracking."""
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("changed_fields", JSONB, nullable=False, server_default="{}"),
        sa.Column("sync_source", sa.String(50), nullable=False, server_default="manual"),
    )

    # Indexes for common queries
    op.create_index(
        "idx_document_versions_document_id",
        "document_versions",
        ["document_id"],
    )
    op.create_index(
        "idx_document_versions_created_at",
        "document_versions",
        ["created_at"],
    )
    op.create_index(
        "idx_document_versions_sync_source",
        "document_versions",
        ["sync_source"],
    )


def downgrade() -> None:
    """Drop document_versions table."""
    op.drop_table("document_versions")
