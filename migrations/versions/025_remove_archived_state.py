"""Remove archived state from bootstrap_state per grooming 2026-05 (MTRNIX-370).

Grooming decided: archive = delete (no separate state). Any rows currently
in 'archived' state are transitioned to 'ready' so they continue to be synced;
operator can manually delete if they really meant archive=stop. The CHECK
constraint is reduced from 4 values to 3.

Revision ID: 025
Revises: 024
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Convert any existing archived rows to ready.
    op.execute("UPDATE bootstrap_state SET state='ready' WHERE state='archived'")
    # Recreate CHECK constraint with 3 values.
    op.drop_constraint("ck_bootstrap_state_state", "bootstrap_state", type_="check")
    op.create_check_constraint(
        "ck_bootstrap_state_state",
        "bootstrap_state",
        "state IN ('bootstrapping','ready','failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bootstrap_state_state", "bootstrap_state", type_="check")
    op.create_check_constraint(
        "ck_bootstrap_state_state",
        "bootstrap_state",
        "state IN ('bootstrapping','ready','archived','failed')",
    )
