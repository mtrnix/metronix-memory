"""Align connections.updated_at with created_at/last_synced_at (timestamptz).

The column was originally created in migration 007 as ``TIMESTAMP WITHOUT TIME
ZONE`` via ``sa.DateTime``.  The runtime code passes ``datetime.now(UTC)`` (tz
aware), which asyncpg rejects when binding to a naive TIMESTAMP column, so
``PUT /api/v1/connections/{id}`` crashes with 500.  Converting the column to
``timestamptz`` matches the sibling timestamp columns and the code's intent.

Revision ID: 015
Revises: 014
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: str = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "connections",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        existing_nullable=True,
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "connections",
        "updated_at",
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
