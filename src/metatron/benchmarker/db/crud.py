"""CRUD operations for Benchmarker.

Functions for creating, reading, updating, deleting and cloning
benchmark sets, questions, test runs and test results.
All BenchmarkSet queries are scoped by workspace_id.
"""

from __future__ import annotations

import structlog
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session, joinedload

from metatron.storage.pg_connection import get_session

from .models import (
    BenchmarkQuestionRow,
    BenchmarkSetRow,
    TestResultRow,
    TestRunRow,
)

logger = structlog.get_logger()

# Metric column names used for average computation
_METRIC_NAMES = (
    "correctness",
    "answer_relevancy",
    "faithfulness",
    "context_precision",
    "context_recall",
    "confidence",
)


# ============================================================================
# Helper
# ============================================================================

def compute_avg_metrics(results: list[TestResultRow]) -> dict:
    """Compute average of non-None values for each of the 6 metrics.

    Returns a dict with keys ``avg_<metric>`` for each metric.
    If all values for a metric are None the average is None.
    """
    avg: dict[str, float | None] = {}
    for metric in _METRIC_NAMES:
        values = [
            getattr(r, metric)
            for r in results
            if getattr(r, metric) is not None
        ]
        avg[f"avg_{metric}"] = sum(values) / len(values) if values else None
    return avg


# ============================================================================
# BenchmarkSet CRUD
# ============================================================================


def upsert_benchmark_set(
    session: Session,
    workspace_id: str,
    questions: list[dict],
    benchmark_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    source: Optional[str] = None,
    source_info: Optional[dict] = None,
    tokens_used: int = 0,
) -> BenchmarkSetRow:
    """Create or update a benchmark set (upsert).

    If *benchmark_id* is provided and exists — update it and sync questions.
    Otherwise create a new benchmark set.
    """
    if benchmark_id:
        existing = (
            session.query(BenchmarkSetRow)
            .filter(BenchmarkSetRow.id == benchmark_id)
            .first()
        )
        if existing:
            # Update existing benchmark
            if name:
                existing.name = name
            if description is not None:
                existing.description = description
            if source:
                existing.source = source
            if source_info is not None:
                existing.source_info = source_info
            existing.tokens_used = tokens_used
            existing.question_count = len(questions)

            # Sync questions: update existing, add new, delete removed
            existing_qs = {
                q.id: q
                for q in session.query(BenchmarkQuestionRow)
                .filter(BenchmarkQuestionRow.benchmark_set_id == benchmark_id)
                .all()
            }
            keep_ids: set[str] = set()
            for qdata in questions:
                qid = qdata.get("id", str(uuid4()))
                keep_ids.add(qid)
                if qid in existing_qs:
                    eq = existing_qs[qid]
                    eq.text = qdata["text"]
                    eq.question_type = qdata["question_type"]
                    eq.references = qdata.get("references")
                    eq.attributes = qdata["attributes"]
                else:
                    session.add(BenchmarkQuestionRow(
                        id=qid,
                        benchmark_set_id=benchmark_id,
                        text=qdata["text"],
                        question_type=qdata["question_type"],
                        references=qdata.get("references"),
                        attributes=qdata["attributes"],
                        created_at=datetime.utcnow(),
                    ))
            for qid, eq in existing_qs.items():
                if qid not in keep_ids:
                    session.delete(eq)

            session.flush()
            logger.info("Benchmark set updated: id=%s", benchmark_id)
            return existing

    # Create new benchmark
    bid = benchmark_id or str(uuid4())
    benchmark = BenchmarkSetRow(
        id=bid,
        workspace_id=workspace_id,
        name=name or f"Benchmark {bid[:8]}",
        source=source or "unknown",
        description=description,
        source_info=source_info,
        tokens_used=tokens_used,
        question_count=len(questions),
        created_at=datetime.utcnow(),
    )
    session.add(benchmark)
    for qdata in questions:
        session.add(BenchmarkQuestionRow(
            id=qdata.get("id", str(uuid4())),
            benchmark_set_id=bid,
            text=qdata["text"],
            question_type=qdata["question_type"],
            references=qdata.get("references"),
            attributes=qdata["attributes"],
            created_at=datetime.utcnow(),
        ))
    session.flush()
    logger.info("Benchmark set created (upsert): id=%s workspace=%s", bid, workspace_id)
    return benchmark


def create_benchmark_set(
    session: Session,
    workspace_id: str,
    name: str,
    source: str,
    description: Optional[str] = None,
    source_info: Optional[dict] = None,
    tokens_used: int = 0,
    question_count: int = 0,
) -> BenchmarkSetRow:
    """Create a new benchmark set scoped to *workspace_id*."""
    benchmark = BenchmarkSetRow(
        id=str(uuid4()),
        workspace_id=workspace_id,
        name=name,
        source=source,
        description=description,
        source_info=source_info,
        tokens_used=tokens_used,
        question_count=question_count,
        created_at=datetime.utcnow(),
    )
    session.add(benchmark)
    session.flush()
    logger.info("Benchmark set created: id=%s workspace=%s", benchmark.id, workspace_id)
    return benchmark


def get_benchmark_sets(session: Session, workspace_id: str) -> list[BenchmarkSetRow]:
    """Return all benchmark sets for *workspace_id*, newest first."""
    return (
        session.query(BenchmarkSetRow)
        .filter(BenchmarkSetRow.workspace_id == workspace_id)
        .order_by(BenchmarkSetRow.created_at.desc())
        .all()
    )


def get_benchmark_set(
    session: Session,
    benchmark_set_id: str,
    workspace_id: str,
) -> Optional[BenchmarkSetRow]:
    """Return a single benchmark set by id, filtered by workspace_id."""
    return (
        session.query(BenchmarkSetRow)
        .filter(
            BenchmarkSetRow.id == benchmark_set_id,
            BenchmarkSetRow.workspace_id == workspace_id,
        )
        .first()
    )


def update_benchmark_set(
    session: Session,
    benchmark_set_id: str,
    workspace_id: str,
    **kwargs,
) -> Optional[BenchmarkSetRow]:
    """Update fields on an existing benchmark set.

    Only the supplied keyword arguments are applied.
    Returns the updated row or ``None`` if not found.
    """
    benchmark = get_benchmark_set(session, benchmark_set_id, workspace_id)
    if benchmark is None:
        return None

    for key, value in kwargs.items():
        if hasattr(benchmark, key):
            setattr(benchmark, key, value)

    session.flush()
    logger.info("Benchmark set updated: id=%s", benchmark_set_id)
    return benchmark


def delete_benchmark_set(
    session: Session,
    benchmark_set_id: str,
    workspace_id: str,
) -> bool:
    """Delete a benchmark set. Returns True if found and deleted."""
    benchmark = get_benchmark_set(session, benchmark_set_id, workspace_id)
    if benchmark is None:
        return False

    session.delete(benchmark)
    session.flush()
    logger.info("Benchmark set deleted: id=%s", benchmark_set_id)
    return True


def clone_benchmark_set(
    session: Session,
    benchmark_set_id: str,
    workspace_id: str,
) -> Optional[BenchmarkSetRow]:
    """Clone a benchmark set with all its questions.

    Creates a new set with name ``"<original> copy"`` and fresh UUIDs for
    the set and every question.  Test runs are NOT copied.
    """
    original = (
        session.query(BenchmarkSetRow)
        .options(joinedload(BenchmarkSetRow.questions))
        .filter(
            BenchmarkSetRow.id == benchmark_set_id,
            BenchmarkSetRow.workspace_id == workspace_id,
        )
        .first()
    )
    if original is None:
        return None

    new_id = str(uuid4())
    clone = BenchmarkSetRow(
        id=new_id,
        workspace_id=workspace_id,
        name=f"{original.name} copy",
        description=original.description,
        source=original.source,
        source_info=original.source_info,
        tokens_used=original.tokens_used,
        question_count=original.question_count,
        created_at=datetime.utcnow(),
    )
    session.add(clone)

    for q in original.questions:
        session.add(
            BenchmarkQuestionRow(
                id=str(uuid4()),
                benchmark_set_id=new_id,
                text=q.text,
                question_type=q.question_type,
                references=q.references,
                attributes=q.attributes,
                created_at=datetime.utcnow(),
            )
        )

    session.flush()
    logger.info("Benchmark set cloned: original=%s clone=%s", benchmark_set_id, new_id)
    return clone


# ============================================================================
# BenchmarkQuestion operations
# ============================================================================


def create_benchmark_questions(
    session: Session,
    benchmark_set_id: str,
    questions: list[dict],
) -> list[BenchmarkQuestionRow]:
    """Bulk-create questions for a benchmark set.

    Each dict must contain ``text``, ``question_type``, ``attributes``
    and optionally ``references`` and ``id``.
    """
    rows: list[BenchmarkQuestionRow] = []
    for q in questions:
        row = BenchmarkQuestionRow(
            id=q.get("id", str(uuid4())),
            benchmark_set_id=benchmark_set_id,
            text=q["text"],
            question_type=q["question_type"],
            references=q.get("references"),
            attributes=q["attributes"],
            created_at=datetime.utcnow(),
        )
        session.add(row)
        rows.append(row)

    session.flush()
    logger.info(
        "Created %d questions for benchmark_set=%s", len(rows), benchmark_set_id
    )
    return rows


def get_benchmark_questions(
    session: Session,
    benchmark_set_id: str,
) -> list[BenchmarkQuestionRow]:
    """Return all questions belonging to *benchmark_set_id*."""
    return (
        session.query(BenchmarkQuestionRow)
        .filter(BenchmarkQuestionRow.benchmark_set_id == benchmark_set_id)
        .all()
    )


# ============================================================================
# TestRun CRUD
# ============================================================================


def create_test_run(
    session: Session,
    benchmark_set_id: str,
    name: str,
    description: Optional[str] = None,
    total_tests: int = 0,
    avg_correctness: Optional[float] = None,
    avg_answer_relevancy: Optional[float] = None,
    avg_faithfulness: Optional[float] = None,
    avg_context_precision: Optional[float] = None,
    avg_context_recall: Optional[float] = None,
    avg_confidence: Optional[float] = None,
) -> TestRunRow:
    """Create a new test run with pre-computed average metrics."""
    run = TestRunRow(
        id=str(uuid4()),
        benchmark_set_id=benchmark_set_id,
        name=name,
        description=description,
        total_tests=total_tests,
        avg_correctness=avg_correctness,
        avg_answer_relevancy=avg_answer_relevancy,
        avg_faithfulness=avg_faithfulness,
        avg_context_precision=avg_context_precision,
        avg_context_recall=avg_context_recall,
        avg_confidence=avg_confidence,
        created_at=datetime.utcnow(),
    )
    session.add(run)
    session.flush()
    logger.info("Test run created: id=%s benchmark_set=%s", run.id, benchmark_set_id)
    return run


def get_test_runs(session: Session, workspace_id: str) -> list[TestRunRow]:
    """Return all test runs for *workspace_id* via join on benchmark_sets."""
    return (
        session.query(TestRunRow)
        .join(BenchmarkSetRow, TestRunRow.benchmark_set_id == BenchmarkSetRow.id)
        .filter(BenchmarkSetRow.workspace_id == workspace_id)
        .order_by(TestRunRow.created_at.desc())
        .all()
    )


def get_test_run(
    session: Session,
    test_run_id: str,
    workspace_id: str,
) -> Optional[TestRunRow]:
    """Return a test run by id with test_results eagerly loaded.

    Filters through benchmark_sets.workspace_id for tenant isolation.
    """
    return (
        session.query(TestRunRow)
        .options(joinedload(TestRunRow.test_results))
        .join(BenchmarkSetRow, TestRunRow.benchmark_set_id == BenchmarkSetRow.id)
        .filter(
            TestRunRow.id == test_run_id,
            BenchmarkSetRow.workspace_id == workspace_id,
        )
        .first()
    )


def delete_test_run(
    session: Session,
    test_run_id: str,
    workspace_id: str,
) -> bool:
    """Delete a test run. Returns True if found and deleted.

    Filters through benchmark_sets.workspace_id for tenant isolation.
    """
    run = (
        session.query(TestRunRow)
        .join(BenchmarkSetRow, TestRunRow.benchmark_set_id == BenchmarkSetRow.id)
        .filter(
            TestRunRow.id == test_run_id,
            BenchmarkSetRow.workspace_id == workspace_id,
        )
        .first()
    )
    if run is None:
        return False

    session.delete(run)
    session.flush()
    logger.info("Test run deleted: id=%s", test_run_id)
    return True


# ============================================================================
# TestResult operations
# ============================================================================


def create_test_results(
    session: Session,
    test_run_id: str,
    results: list[dict],
) -> list[TestResultRow]:
    """Bulk-create test results for a test run.

    Each dict should contain ``actual_answer`` (required) and optionally
    ``question``, the 6 metric floats, ``claim_scores``, and ``context``.
    """
    rows: list[TestResultRow] = []
    for r in results:
        row = TestResultRow(
            id=r.get("id", str(uuid4())),
            test_run_id=test_run_id,
            question=r.get("question"),
            actual_answer=r["actual_answer"],
            correctness=r.get("correctness"),
            answer_relevancy=r.get("answer_relevancy"),
            faithfulness=r.get("faithfulness"),
            context_precision=r.get("context_precision"),
            context_recall=r.get("context_recall"),
            confidence=r.get("confidence"),
            claim_scores=r.get("claim_scores"),
            context=r.get("context"),
        )
        session.add(row)
        rows.append(row)

    session.flush()
    logger.info("Created %d test results for test_run=%s", len(rows), test_run_id)
    return rows
