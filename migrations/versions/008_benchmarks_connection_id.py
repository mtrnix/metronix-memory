"""Replace source/source_info with connection_id in benchmark_sets.

Revision ID: 008
Revises: 007
Create Date: 2026-03-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop source/source_info, add connection_id to benchmark_sets."""
    # Remove old columns
    op.drop_column("benchmark_sets", "source")
    op.drop_column("benchmark_sets", "source_info")

    # Add connection_id (NOT NULL)
    op.add_column(
        "benchmark_sets",
        sa.Column("connection_id", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    """Revert: drop connection_id, restore source/source_info."""
    op.drop_column("benchmark_sets", "connection_id")
    op.add_column(
        "benchmark_sets",
        sa.Column("source", sa.String(50), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "benchmark_sets",
        sa.Column("source_info", sa.JSON, nullable=True),
    )
