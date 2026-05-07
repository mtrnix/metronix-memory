"""Add last_accessed_at and content_simhash to memory_records (MTRNIX-277).

Adds two health-tracking columns:
- ``last_accessed_at`` — timestamp updated when a record is retrieved by
  hybrid search. Used to identify "stale" (never-accessed) memories.
- ``content_simhash`` — 64-bit SimHash fingerprint stored as PG BIGINT.
  Used by the health service to detect near-duplicate memories without
  a full pairwise content comparison.

Both columns are NULLABLE — existing rows get NULL, which is handled
gracefully by all callers (NULL simhash rows are skipped in dup detection;
NULL last_accessed_at falls back to created_at in the unused-count predicate).

Revision ID: 021
Revises: 020
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_records",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "memory_records",
        sa.Column("content_simhash", sa.BigInteger, nullable=True),
    )
    op.create_index(
        "ix_memory_records_last_accessed",
        "memory_records",
        ["workspace_id", "agent_id", sa.text("last_accessed_at DESC")],
        postgresql_where=sa.text("last_accessed_at IS NOT NULL"),
    )
    op.create_index(
        "ix_memory_records_simhash",
        "memory_records",
        ["workspace_id", "agent_id", "content_simhash"],
        postgresql_where=sa.text("content_simhash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_memory_records_simhash", table_name="memory_records")
    op.drop_index("ix_memory_records_last_accessed", table_name="memory_records")
    op.drop_column("memory_records", "content_simhash")
    op.drop_column("memory_records", "last_accessed_at")
