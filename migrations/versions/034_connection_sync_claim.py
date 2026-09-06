"""connections.sync_claim_id — ownership token for the 'syncing' lock.

The sync lock IS ``connections.status = 'syncing'``; there is no separate lock
object. ``sync_claim_id`` records *which* sync attempt currently holds it, so a
release path can be conditioned on still owning the claim instead of writing the
connection unconditionally (#425). NULL means the lock is free / not held by a
token-aware claimer.

Nullable, no backfill: NULL is the correct value for every existing row. A row
left ``status='syncing'`` by a pre-migration deployment simply has a NULL token
and is reclaimed by ``recover_interrupted_syncs`` on the next API restart, the
same as any SIGKILL'd sync.

Revision ID: 034
Revises: 033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: str | None = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("sync_claim_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connections", "sync_claim_id")
