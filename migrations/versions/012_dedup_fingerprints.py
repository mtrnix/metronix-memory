"""Add dedup_fingerprints table for persistent deduplication index.

Revision ID: 012
Revises: 011
Create Date: 2026-03-27
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "dedup_fingerprints"):
        op.drop_table("dedup_fingerprints")

    op.create_table(
        "dedup_fingerprints",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("doc_label", sa.Text, nullable=False),
        sa.Column("fingerprint", sa.BigInteger, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "fingerprint",
            "doc_label",
            name="uq_dedup_fp_ws_fp_doc",
        ),
    )

    op.create_index(
        "ix_dedup_fp_workspace",
        "dedup_fingerprints",
        ["workspace_id"],
    )
    op.create_index(
        "ix_dedup_fp_doc_label",
        "dedup_fingerprints",
        ["workspace_id", "doc_label"],
    )


def downgrade() -> None:
    op.drop_table("dedup_fingerprints")
