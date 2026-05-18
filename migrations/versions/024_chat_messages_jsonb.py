"""Migrate chat_messages JSON columns to JSONB (MTRNIX-354, T4).

Converts ``citations_json`` and ``tool_calls_json`` columns from JSON to JSONB.
JSONB enables server-side operators and is semantically equivalent for this use-case.
The ``_parse_json_col`` helper in ``chat/persistence.py`` handles both native dict/list
(JSONB path) and raw string (JSON path) — no code changes needed there.

Revision ID: 024
Revises: 023
Create Date: 2026-05-19
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "024"
down_revision: str | None = "023"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat_messages "
        "ALTER COLUMN citations_json TYPE jsonb USING citations_json::jsonb"
    )
    op.execute(
        "ALTER TABLE chat_messages "
        "ALTER COLUMN tool_calls_json TYPE jsonb USING tool_calls_json::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE chat_messages "
        "ALTER COLUMN citations_json TYPE json USING citations_json::json"
    )
    op.execute(
        "ALTER TABLE chat_messages "
        "ALTER COLUMN tool_calls_json TYPE json USING tool_calls_json::json"
    )
