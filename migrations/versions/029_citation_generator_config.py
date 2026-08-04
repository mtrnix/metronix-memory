"""Workspace-scoped answer and citation generator overrides.

Revision ID: 029
Revises: 028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: str | None = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "citation_generator_configs",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False, server_default=""),
        sa.Column("credential_id", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("provider IN ('ollama', 'custom')", name="ck_citation_generator_provider"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )


def downgrade() -> None:
    op.drop_table("citation_generator_configs")
