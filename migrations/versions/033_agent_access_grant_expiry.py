"""Add expiry support for delegated agent-access grants.

Revision ID: 033
Revises: 032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "033"
down_revision: str | None = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_access_grants",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_access_grants_expires_at",
        "agent_access_grants",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_access_grants_expires_at", table_name="agent_access_grants")
    op.drop_column("agent_access_grants", "expires_at")
