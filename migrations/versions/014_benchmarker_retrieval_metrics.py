"""Add retrieval metrics (ndcg, mrr, precision) to test_runs and test_results.

Revision ID: 014
Revises: 013
Create Date: 2026-04-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: str = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # test_runs: avg retrieval metrics
    op.add_column("test_runs", sa.Column("avg_ndcg_at_10", sa.Float(), nullable=True))
    op.add_column("test_runs", sa.Column("avg_mrr", sa.Float(), nullable=True))
    op.add_column("test_runs", sa.Column("avg_precision_at_k", sa.Float(), nullable=True))

    # test_results: per-question retrieval metrics
    op.add_column("test_results", sa.Column("ndcg_at_10", sa.Float(), nullable=True))
    op.add_column("test_results", sa.Column("mrr", sa.Float(), nullable=True))
    op.add_column("test_results", sa.Column("precision_at_k", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("test_results", "precision_at_k")
    op.drop_column("test_results", "mrr")
    op.drop_column("test_results", "ndcg_at_10")

    op.drop_column("test_runs", "avg_precision_at_k")
    op.drop_column("test_runs", "avg_mrr")
    op.drop_column("test_runs", "avg_ndcg_at_10")
