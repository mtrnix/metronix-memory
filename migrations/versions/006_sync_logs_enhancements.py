"""Add source_title, qdrant_chunks to sync_logs and make connection_id nullable.

Revision ID: 006
Revises: 005
Create Date: 2026-03-04 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add source_title column (human-readable sync source name)
    op.add_column(
        "sync_logs",
        sa.Column("source_title", sa.String(255), nullable=True),
    )
    
    # Add qdrant_chunks column (total chunks created in this sync)
    op.add_column(
        "sync_logs",
        sa.Column("qdrant_chunks", sa.Integer, nullable=False, server_default="0"),
    )
    
    # Make connection_id nullable to support env-based syncs
    op.alter_column(
        "sync_logs",
        "connection_id",
        existing_type=sa.String(64),
        nullable=True,
    )


def downgrade() -> None:
    # Revert connection_id to non-nullable (will fail if NULL values exist)
    op.alter_column(
        "sync_logs",
        "connection_id",
        existing_type=sa.String(64),
        nullable=False,
    )
    
    op.drop_column("sync_logs", "qdrant_chunks")
    op.drop_column("sync_logs", "source_title")
