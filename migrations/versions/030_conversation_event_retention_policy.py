"""Allow conversation events with a forever retention policy.

Revision ID: 030
Revises: 029
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "030"
down_revision: str | None = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "conversation_events",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "conversation_events",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
