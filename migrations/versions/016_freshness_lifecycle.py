"""Freshness lifecycle columns + review_entries + machine_events (MTRNIX-304).

Adds seven lifecycle columns to ``memory_records`` and introduces the
``review_entries`` and ``machine_events`` tables used by the Phase A
freshness pipeline. Defaults are backward-compatible: existing rows land
with ``status='active'`` and ``freshness_score=0.5``.

Revision ID: 016
Revises: 015
Create Date: 2026-04-20
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_records",
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
    )
    op.add_column(
        "memory_records",
        sa.Column(
            "freshness_score",
            sa.Float,
            nullable=False,
            server_default=sa.text("0.5"),
        ),
    )
    op.add_column(
        "memory_records",
        sa.Column("superseded_by", sa.Text, nullable=True),
    )
    op.add_column(
        "memory_records",
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "memory_records",
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "memory_records",
        sa.Column(
            "evidence_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "memory_records",
        sa.Column("verification_state", sa.Text, nullable=True),
    )

    op.create_index(
        "ix_memory_records_status",
        "memory_records",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_memory_records_valid_until",
        "memory_records",
        ["workspace_id", "valid_until"],
        postgresql_where=sa.text("valid_until IS NOT NULL"),
    )

    op.create_table(
        "review_entries",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("record_id", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("related_record_id", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "confidence",
            sa.Float,
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_review_entries_workspace",
        "review_entries",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_review_entries_record",
        "review_entries",
        ["workspace_id", "record_id"],
    )

    op.create_table(
        "machine_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column(
            "actor",
            sa.Text,
            nullable=False,
            server_default="freshness_worker",
        ),
        sa.Column(
            "target_kind",
            sa.Text,
            nullable=False,
            server_default="memory_record",
        ),
        sa.Column("target_id", sa.Text, nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_machine_events_workspace_time",
        "machine_events",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_machine_events_target",
        "machine_events",
        ["target_kind", "target_id", "created_at"],
    )
    op.create_index(
        "ix_machine_events_type",
        "machine_events",
        ["workspace_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_machine_events_type", table_name="machine_events")
    op.drop_index("ix_machine_events_target", table_name="machine_events")
    op.drop_index(
        "ix_machine_events_workspace_time",
        table_name="machine_events",
    )
    op.drop_table("machine_events")

    op.drop_index("ix_review_entries_record", table_name="review_entries")
    op.drop_index("ix_review_entries_workspace", table_name="review_entries")
    op.drop_table("review_entries")

    op.drop_index(
        "ix_memory_records_valid_until",
        table_name="memory_records",
    )
    op.drop_index("ix_memory_records_status", table_name="memory_records")
    op.drop_column("memory_records", "verification_state")
    op.drop_column("memory_records", "evidence_count")
    op.drop_column("memory_records", "valid_until")
    op.drop_column("memory_records", "valid_from")
    op.drop_column("memory_records", "superseded_by")
    op.drop_column("memory_records", "freshness_score")
    op.drop_column("memory_records", "status")
