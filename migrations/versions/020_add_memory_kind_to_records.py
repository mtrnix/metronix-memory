"""Add kind column to memory_records (MTRNIX-275).

Adds ``kind VARCHAR(16) NOT NULL DEFAULT 'fact'`` to ``memory_records``.
Existing rows become ``kind=fact`` — semantically correct (all pre-MTRNIX-275
records are ordinary facts).

Revision ID: 020
Revises: 019
Create Date: 2026-04-28
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_records",
        sa.Column("kind", sa.String(16), nullable=False, server_default="fact"),
    )


def downgrade() -> None:
    op.drop_column("memory_records", "kind")
