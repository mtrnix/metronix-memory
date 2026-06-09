"""Add autosync schedule columns to connections; add trigger to sync_logs.

connections: sync_cron TEXT server_default '0 3 * * *', next_run_at TIMESTAMPTZ NULL.
sync_logs: trigger TEXT NOT NULL DEFAULT 'manual'.

Backfill: existing connector rows (not channels) get sync_cron='0 3 * * *';
channel types (telegram, discord, slack) get sync_cron=NULL.
next_run_at is left NULL for all rows — the scheduler treats NULL as "due now".

Revision ID: 025
Revises: 024
Create Date: 2026-06-09
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "025"
down_revision: str | None = "024"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Channel types — these never have a sync schedule.
# Hardcoded here to avoid importing app code inside a migration.
_CHANNEL_TYPES = ("telegram", "discord", "slack")


def upgrade() -> None:
    # --- connections ---
    op.add_column(
        "connections",
        sa.Column(
            "sync_cron",
            sa.Text(),
            nullable=True,
            server_default="0 3 * * *",
        ),
    )
    op.add_column(
        "connections",
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Backfill: channel types → NULL; all others already have the server_default
    # but the server_default only applies to new rows. For existing rows we must
    # explicitly SET them. Two steps:
    # 1. Set all existing rows to the default (server_default doesn't fill them).
    # 2. Null out channel types.
    op.execute(
        sa.text("UPDATE connections SET sync_cron = '0 3 * * *'")
    )
    op.execute(
        sa.text(
            "UPDATE connections SET sync_cron = NULL"
            " WHERE connector_type = ANY(:channels)"
        ).bindparams(sa.bindparam("channels", value=list(_CHANNEL_TYPES), expanding=False))
    )

    # --- sync_logs ---
    op.add_column(
        "sync_logs",
        sa.Column(
            "trigger",
            sa.Text(),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    op.drop_column("sync_logs", "trigger")
    op.drop_column("connections", "next_run_at")
    op.drop_column("connections", "sync_cron")
