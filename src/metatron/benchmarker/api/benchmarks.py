"""Benchmark CRUD API — /benchmarks endpoints.

Provides list, get, create, delete, and clone operations for benchmark sets.
All endpoints require a workspace_id query parameter for tenant isolation.
"""

from __future__ import annotations

import structlog

from fastapi import APIRouter, HTTPException, Query

from metatron.benchmarker.db import crud
from metatron.benchmarker.schemas.benchmark import SaveBenchmarkRequest
from metatron.storage.pg_connection import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/benchmarks", tags=["benchmarker-benchmarks"])


@router.get("/")
def list_benchmarks(workspace_id: str = Query(..., description="Workspace ID")) -> dict:
    """List all benchmark sets for a workspace."""
    try:
        with get_session() as session:
            benchmarks = crud.get_benchmark_sets(session, workspace_id)
            return {
                "benchmarks": [
                    {
                        "id": b.id,
                        "workspace_id": b.workspace_id,
                        "connection_id": b.connection_id,
                        "name": b.name,
                        "description": b.description,
                        "question_count": b.question_count,
                        "tokens_used": b.tokens_used,
                        "created_at": b.created_at.isoformat(),
                    }
                    for b in benchmarks
                ],
                "count": len(benchmarks),
            }
    except Exception as exc:
        logger.error("Failed to list benchmarks: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list benchmarks") from exc


@router.get("/{benchmark_id}")
def get_benchmark(
    benchmark_id: str,
    workspace_id: str = Query(..., description="Workspace ID"),
) -> dict:
    """Get a benchmark set with all its questions."""
    try:
        with get_session() as session:
            benchmark = crud.get_benchmark_set(session, benchmark_id, workspace_id)
            if benchmark is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Benchmark {benchmark_id} not found",
                )

            questions = crud.get_benchmark_questions(session, benchmark_id)

            return {
                "benchmark": {
                    "id": benchmark.id,
                    "workspace_id": benchmark.workspace_id,
                    "connection_id": benchmark.connection_id,
                    "name": benchmark.name,
                    "description": benchmark.description,
                    "tokens_used": benchmark.tokens_used,
                    "question_count": benchmark.question_count,
                    "created_at": benchmark.created_at.isoformat(),
                },
                "questions": [
                    {
                        "id": q.id,
                        "text": q.text,
                        "question_type": q.question_type,
                        "references": q.references,
                        "attributes": q.attributes,
                    }
                    for q in questions
                ],
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get benchmark %s: %s", benchmark_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get benchmark") from exc


@router.post("/")
def create_benchmark(
    request: SaveBenchmarkRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
) -> dict:
    """Create or update a benchmark set with questions (upsert)."""
    if not request.questions:
        raise HTTPException(status_code=422, detail="Questions list cannot be empty")

    try:
        with get_session() as session:
            benchmark = crud.upsert_benchmark_set(
                session,
                workspace_id=workspace_id,
                connection_id=request.connection_id,
                questions=request.questions,
                benchmark_id=request.id,
                name=request.name,
                description=request.description,
                tokens_used=request.tokens_used,
            )
            session.commit()

            return {
                "success": True,
                "message": "Benchmark successfully saved",
                "benchmark_id": benchmark.id,
                "id": benchmark.id,
                "workspace_id": benchmark.workspace_id,
                "connection_id": benchmark.connection_id,
                "name": benchmark.name,
                "question_count": benchmark.question_count,
                "created_at": benchmark.created_at.isoformat(),
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to create benchmark: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create benchmark") from exc


@router.delete("/{benchmark_id}")
def delete_benchmark(
    benchmark_id: str,
    workspace_id: str = Query(..., description="Workspace ID"),
) -> dict:
    """Delete a benchmark set and all its questions."""
    try:
        with get_session() as session:
            deleted = crud.delete_benchmark_set(session, benchmark_id, workspace_id)
            if not deleted:
                raise HTTPException(
                    status_code=404,
                    detail=f"Benchmark {benchmark_id} not found",
                )
            return {"success": True, "id": benchmark_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delete benchmark %s: %s", benchmark_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete benchmark") from exc


@router.post("/{benchmark_id}/clone")
def clone_benchmark(
    benchmark_id: str,
    workspace_id: str = Query(..., description="Workspace ID"),
) -> dict:
    """Clone a benchmark set with all its questions."""
    try:
        with get_session() as session:
            clone = crud.clone_benchmark_set(session, benchmark_id, workspace_id)
            if clone is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Benchmark {benchmark_id} not found",
                )
            return {
                "id": clone.id,
                "workspace_id": clone.workspace_id,
                "connection_id": clone.connection_id,
                "name": clone.name,
                "question_count": clone.question_count,
                "created_at": clone.created_at.isoformat(),
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to clone benchmark %s: %s", benchmark_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clone benchmark") from exc
