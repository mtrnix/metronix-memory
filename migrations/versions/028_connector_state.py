"""connector_state — per-connection opaque sync cursor.

Revision ID: 028
Revises: 027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "028"
down_revision: str | None = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_state",
        sa.Column(
            "connection_id",
            sa.String(64),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("connector_state")
