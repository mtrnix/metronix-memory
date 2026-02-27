"""Add benchmarker tables: benchmark_sets, benchmark_questions, test_runs, test_results.

Revision ID: 005
Revises: 004
Create Date: 2026-02-27 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create benchmarker tables for benchmark sets, questions, test runs and results."""

    # --- Benchmark sets ---
    op.create_table(
        "benchmark_sets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_info", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("question_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_benchmark_sets_workspace",
        "benchmark_sets",
        ["workspace_id"],
    )

    # --- Benchmark questions ---
    op.create_table(
        "benchmark_questions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "benchmark_set_id",
            sa.String(64),
            sa.ForeignKey("benchmark_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("question_type", sa.String(20), nullable=False),
        sa.Column("references", sa.JSON, nullable=True),
        sa.Column("attributes", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_benchmark_questions_set",
        "benchmark_questions",
        ["benchmark_set_id"],
    )

    # --- Test runs ---
    op.create_table(
        "test_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "benchmark_set_id",
            sa.String(64),
            sa.ForeignKey("benchmark_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("total_tests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_correctness", sa.Float, nullable=True),
        sa.Column("avg_answer_relevancy", sa.Float, nullable=True),
        sa.Column("avg_faithfulness", sa.Float, nullable=True),
        sa.Column("avg_context_precision", sa.Float, nullable=True),
        sa.Column("avg_context_recall", sa.Float, nullable=True),
        sa.Column("avg_confidence", sa.Float, nullable=True),
    )
    op.create_index(
        "ix_test_runs_benchmark_set",
        "test_runs",
        ["benchmark_set_id"],
    )

    # --- Test results ---
    op.create_table(
        "test_results",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "test_run_id",
            sa.String(64),
            sa.ForeignKey("test_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.JSON, nullable=True),
        sa.Column("actual_answer", sa.Text, nullable=False),
        sa.Column("correctness", sa.Float, nullable=True),
        sa.Column("answer_relevancy", sa.Float, nullable=True),
        sa.Column("faithfulness", sa.Float, nullable=True),
        sa.Column("context_precision", sa.Float, nullable=True),
        sa.Column("context_recall", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("claim_scores", sa.JSON, nullable=True),
        sa.Column("context", sa.JSON, nullable=True),
    )
    op.create_index(
        "ix_test_results_run",
        "test_results",
        ["test_run_id"],
    )


def downgrade() -> None:
    """Drop all benchmarker tables in reverse dependency order."""
    op.drop_table("test_results")
    op.drop_table("test_runs")
    op.drop_table("benchmark_questions")
    op.drop_table("benchmark_sets")
