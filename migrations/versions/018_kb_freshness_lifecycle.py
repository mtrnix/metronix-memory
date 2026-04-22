"""Freshness lifecycle columns on raw_documents + review_entries target_kind/target_id.

MTRNIX-313 (Phase B): extend the freshness pipeline to the KB ``raw_documents``
surface. Adds seven lifecycle columns plus two indexes on ``raw_documents``;
renames ``review_entries.record_id`` to ``target_id`` and introduces a
``target_kind`` discriminator so memory and KB review items can share the
table.

Revision ID: 018
Revises: 017
Create Date: 2026-04-22
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- raw_documents lifecycle columns ---
    op.add_column(
        "raw_documents",
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
    )
    op.create_check_constraint(
        "ck_raw_docs_status",
        "raw_documents",
        "status IN ('candidate','active','stale','superseded',"
        "'archived','conflicted','review_needed')",
    )
    op.add_column(
        "raw_documents",
        sa.Column(
            "freshness_score",
            sa.Float,
            nullable=False,
            server_default=sa.text("0.5"),
        ),
    )
    op.add_column("raw_documents", sa.Column("superseded_by", sa.Text, nullable=True))
    op.add_column(
        "raw_documents",
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column(
            "evidence_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "raw_documents",
        sa.Column("verification_state", sa.Text, nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column(
            "last_freshness_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_raw_docs_ws_status",
        "raw_documents",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_raw_docs_ws_valid_until",
        "raw_documents",
        ["workspace_id", "valid_until"],
        postgresql_where=sa.text("valid_until IS NOT NULL"),
    )

    # --- review_entries: rename record_id -> target_id, add target_kind ---
    op.add_column(
        "review_entries",
        sa.Column(
            "target_kind",
            sa.Text,
            nullable=False,
            server_default="memory_record",
        ),
    )
    # Drop the existing (workspace_id, record_id) index first — cannot rename
    # a column while a regular index references it in a backward-compatible
    # way across all PG versions the project supports.
    op.drop_index("ix_review_entries_record", table_name="review_entries")
    op.alter_column("review_entries", "record_id", new_column_name="target_id")
    op.create_index(
        "ix_review_entries_target",
        "review_entries",
        ["workspace_id", "target_kind", "target_id"],
    )


def downgrade() -> None:
    # --- review_entries rollback ---
    op.drop_index("ix_review_entries_target", table_name="review_entries")
    op.alter_column("review_entries", "target_id", new_column_name="record_id")
    op.create_index(
        "ix_review_entries_record",
        "review_entries",
        ["workspace_id", "record_id"],
    )
    op.drop_column("review_entries", "target_kind")

    # --- raw_documents rollback ---
    op.drop_index("ix_raw_docs_ws_valid_until", table_name="raw_documents")
    op.drop_index("ix_raw_docs_ws_status", table_name="raw_documents")
    op.drop_column("raw_documents", "last_freshness_run_at")
    op.drop_column("raw_documents", "verification_state")
    op.drop_column("raw_documents", "evidence_count")
    op.drop_column("raw_documents", "valid_until")
    op.drop_column("raw_documents", "superseded_by")
    op.drop_column("raw_documents", "freshness_score")
    op.drop_constraint("ck_raw_docs_status", "raw_documents", type_="check")
    op.drop_column("raw_documents", "status")
