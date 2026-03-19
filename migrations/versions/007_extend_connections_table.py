"""Extend connections table with name, enabled, error_message, updated_at.

Revision ID: 007
Revises: 006
Create Date: 2026-03-12 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "connections",
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
    )
    op.add_column(
        "connections",
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.add_column(
        "connections",
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    # Remove server_default for name after backfill (existing rows get empty string)
    op.alter_column("connections", "name", server_default=None)


def downgrade() -> None:
    op.drop_column("connections", "updated_at")
    op.drop_column("connections", "error_message")
    op.drop_column("connections", "enabled")
    op.drop_column("connections", "name")
