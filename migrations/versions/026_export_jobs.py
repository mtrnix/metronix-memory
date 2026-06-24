"""Add export_jobs table for the data-export feature.

Revision ID: 026
Revises: 025
Create Date: 2026-06-24
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "026"
down_revision: str | None = "025"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "scope",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("scope_key", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("workspace_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("memory_record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("document_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("archive_path", sa.Text, nullable=True),
        sa.Column("download_token", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # UNIQUE so the DB enforces at most one active (pending/running) job per scope,
    # closing the check-then-create race in ExportService.start.
    op.create_index(
        "ix_export_jobs_active_scope",
        "export_jobs",
        ["scope_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','running')"),
    )
    op.create_index("ix_export_jobs_status", "export_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_status", table_name="export_jobs")
    op.drop_index("ix_export_jobs_active_scope", table_name="export_jobs")
    op.drop_table("export_jobs")
