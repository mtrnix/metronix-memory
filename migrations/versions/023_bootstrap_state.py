"""Add bootstrap_state table for ASOC workspace lifecycle (MTRNIX-352, T2).

Tracks the bootstrapping / ready / archived / failed state machine for each
workspace provisioned by the ASOC pilot. A single row per workspace_id serves
as the authoritative lifecycle record for the BootstrapRunner and retry cron.

Revision ID: 023
Revises: 022
Create Date: 2026-05-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bootstrap_state",
        sa.Column("workspace_id", sa.Text, primary_key=True),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("progress", sa.REAL, nullable=False, server_default=sa.text("0.0")),
        sa.Column("current_step", sa.Text, nullable=True),
        sa.Column("last_processed_resource", sa.Text, nullable=True),
        sa.Column("last_processed_id", sa.Text, nullable=True),
        sa.Column(
            "indexed_count", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("total_count", sa.Integer, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "retry_count", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "state IN ('bootstrapping','ready','archived','failed')",
            name="ck_bootstrap_state_state",
        ),
    )
    op.create_index(
        "ix_bootstrap_state_failed_due",
        "bootstrap_state",
        ["next_retry_at"],
        postgresql_where=sa.text("state = 'failed'"),
    )
    op.create_index("ix_bootstrap_state_state", "bootstrap_state", ["state"])


def downgrade() -> None:
    op.drop_index("ix_bootstrap_state_state", table_name="bootstrap_state")
    op.drop_index("ix_bootstrap_state_failed_due", table_name="bootstrap_state")
    op.drop_table("bootstrap_state")
