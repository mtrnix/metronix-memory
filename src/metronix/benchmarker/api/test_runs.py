"""Test runs CRUD API — /test-runs endpoints.

Provides list, get, save, and delete operations for test runs.
All endpoints require a workspace_id query parameter for tenant isolation.
The POST endpoint accepts results from the frontend and saves them to the DB.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from metronix.benchmarker.db import crud
from metronix.benchmarker.db.models import BenchmarkSetRow
from metronix.storage.pg_connection import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/test-runs", tags=["benchmarker-test-runs"])


# ============================================================================
# Pydantic schemas for POST
# ============================================================================


class TestResultData(BaseModel):
    """Single test result payload for saving."""

    question: dict | None = None
    actual_answer: str
    correctness: float | None = None
    answer_relevancy: float | None = None
    faithfulness: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    confidence: float | None = None
    claim_scores: list | None = None
    context: dict | None = None


class SaveTestRunRequest(BaseModel):
    """Request body for POST /test-runs."""

    benchmark_set_id: str
    workspace_id: str
    name: str
    description: str | None = None
    results: list[TestResultData]


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/")
def save_test_run(request: SaveTestRunRequest) -> dict:
    """Save a test run with pre-computed results from the frontend."""
    try:
        logger.info("Saving test run: %s (%d results)", request.name, len(request.results))

        if not request.results:
            raise HTTPException(status_code=400, detail="Results list cannot be empty")

        results_dicts = [r.model_dump() for r in request.results]

        # Compute averages from the already-computed metric values
        metric_names = [
            "correctness",
            "answer_relevancy",
            "faithfulness",
            "context_precision",
            "context_recall",
            "confidence",
            "ndcg_at_10",
            "mrr",
            "precision_at_k",
        ]
        avg_metrics: dict[str, float | None] = {}
        for metric in metric_names:
            values = [r[metric] for r in results_dicts if r.get(metric) is not None]
            avg_metrics[metric] = sum(values) / len(values) if values else None

        with get_session() as session:
            # Validate benchmark exists and belongs to workspace
            bs = (
                session.query(BenchmarkSetRow)
                .filter(
                    BenchmarkSetRow.id == request.benchmark_set_id,
                    BenchmarkSetRow.workspace_id == request.workspace_id,
                )
                .first()
            )
            if not bs:
                raise HTTPException(
                    status_code=404,
                    detail=f"Benchmark {request.benchmark_set_id} not found in workspace {request.workspace_id}",  # noqa: E501
                )

            run = crud.create_test_run(
                session,
                benchmark_set_id=request.benchmark_set_id,
                name=request.name,
                description=request.description,
                total_tests=len(results_dicts),
                avg_correctness=avg_metrics["correctness"],
                avg_answer_relevancy=avg_metrics["answer_relevancy"],
                avg_faithfulness=avg_metrics["faithfulness"],
                avg_context_precision=avg_metrics["context_precision"],
                avg_context_recall=avg_metrics["context_recall"],
                avg_confidence=avg_metrics["confidence"],
                avg_ndcg_at_10=avg_metrics["ndcg_at_10"],
                avg_mrr=avg_metrics["mrr"],
                avg_precision_at_k=avg_metrics["precision_at_k"],
            )

            crud.create_test_results(session, run.id, results_dicts)
            session.commit()

            logger.info("Test run saved: %s", run.id)

            return {
                "success": True,
                "message": "Test run successfully saved",
                "test_run_id": run.id,
                "name": run.name,
                "total_tests": run.total_tests,
                "created_at": run.created_at.isoformat(),
            }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error saving test run: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Error saving test run") from exc


@router.get("/")
def list_test_runs(workspace_id: str = Query(..., description="Workspace ID")) -> dict:
    """List all test runs for a workspace."""
    try:
        with get_session() as session:
            runs = crud.get_test_runs(session, workspace_id)
            return {
                "test_runs": [
                    {
                        "id": r.id,
                        "benchmark_set_id": r.benchmark_set_id,
                        "name": r.name,
                        "description": r.description,
                        "total_tests": r.total_tests,
                        "created_at": r.created_at.isoformat(),
                        "avg_correctness": r.avg_correctness,
                        "avg_answer_relevancy": r.avg_answer_relevancy,
                        "avg_faithfulness": r.avg_faithfulness,
                        "avg_context_precision": r.avg_context_precision,
                        "avg_context_recall": r.avg_context_recall,
                        "avg_confidence": r.avg_confidence,
                    }
                    for r in runs
                ],
                "count": len(runs),
            }
    except Exception as exc:
        logger.error("Failed to list test runs: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list test runs") from exc


@router.get("/{test_run_id}")
def get_test_run(
    test_run_id: str,
    workspace_id: str = Query(..., description="Workspace ID"),
) -> dict:
    """Get a test run with all its results."""
    try:
        with get_session() as session:
            run = crud.get_test_run(session, test_run_id, workspace_id)
            if run is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Test run {test_run_id} not found",
                )

            return {
                "test_run": {
                    "id": run.id,
                    "benchmark_set_id": run.benchmark_set_id,
                    "name": run.name,
                    "description": run.description,
                    "total_tests": run.total_tests,
                    "created_at": run.created_at.isoformat(),
                    "avg_correctness": run.avg_correctness,
                    "avg_answer_relevancy": run.avg_answer_relevancy,
                    "avg_faithfulness": run.avg_faithfulness,
                    "avg_context_precision": run.avg_context_precision,
                    "avg_context_recall": run.avg_context_recall,
                    "avg_confidence": run.avg_confidence,
                },
                "results": [
                    {
                        "id": tr.id,
                        "question": tr.question,
                        "actual_answer": tr.actual_answer,
                        "correctness": tr.correctness,
                        "answer_relevancy": tr.answer_relevancy,
                        "faithfulness": tr.faithfulness,
                        "context_precision": tr.context_precision,
                        "context_recall": tr.context_recall,
                        "confidence": tr.confidence,
                        "claim_scores": tr.claim_scores,
                        "context": tr.context,
                    }
                    for tr in (run.test_results or [])
                ],
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get test run %s: %s", test_run_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get test run") from exc


@router.delete("/{test_run_id}")
def delete_test_run(
    test_run_id: str,
    workspace_id: str = Query(..., description="Workspace ID"),
) -> dict:
    """Delete a test run and all its results."""
    try:
        with get_session() as session:
            deleted = crud.delete_test_run(session, test_run_id, workspace_id)
            if not deleted:
                raise HTTPException(
                    status_code=404,
                    detail=f"Test run {test_run_id} not found",
                )
            return {"success": True, "id": test_run_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delete test run %s: %s", test_run_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete test run") from exc
