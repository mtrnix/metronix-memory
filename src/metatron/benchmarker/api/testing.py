"""Benchmark testing API — POST /run-tests.

Accepts a RunTestsRequest, loads the benchmark set and its questions,
runs them through the RAG pipeline via TestRunner, saves test results,
and returns the test run with per-question metrics.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException

from metatron.benchmarker.db import crud
from metatron.benchmarker.schemas.benchmark import (
    BenchmarkQuestion,
    Claim,
    ClaimSource,
    QuestionAttributes,
    RunTestsRequest,
)
from metatron.benchmarker.services.context_fetcher import ContextFetcher
from metatron.benchmarker.services.metrics.controller import MetricsController
from metatron.benchmarker.services.runner import TestRunner
from metatron.core.config import get_settings
from metatron.storage.pg_connection import get_session

logger = structlog.get_logger()

router = APIRouter(tags=["benchmarker-testing"])


def _row_to_benchmark_question(row) -> BenchmarkQuestion:
    """Convert a BenchmarkQuestionRow to a BenchmarkQuestion pydantic model."""
    attrs = row.attributes or {}

    claims = []
    for c in attrs.get("claims", []):
        sources = [ClaimSource(**s) for s in c.get("sources", [])]
        claims.append(
            Claim(
                statement=c.get("statement", ""),
                sources=sources,
                score=c.get("score", 0),
                source_ids=c.get("source_ids", []),
            )
        )

    attributes = QuestionAttributes(
        input_question=attrs.get("input_question", ""),
        period=attrs.get("period"),
        location=attrs.get("location"),
        named_entities=attrs.get("named_entities", []),
        abstract_categories=attrs.get("abstract_categories", []),
        background_information=attrs.get("background_information"),
        reference_coverage=attrs.get("reference_coverage", 0.0),
        relevant_reference_count=attrs.get("relevant_reference_count", 0),
        reference_count=attrs.get("reference_count", 0),
        min_reference_similarity=attrs.get("min_reference_similarity", 0.0),
        max_reference_similarity=attrs.get("max_reference_similarity", 0.0),
        mean_reference_similarity=attrs.get("mean_reference_similarity", 0.0),
        intra_inter_similarity_ratio=attrs.get("intra_inter_similarity_ratio", 0.0),
        claim_count=attrs.get("claim_count", 0),
        claims=claims,
        is_representative=attrs.get("is_representative", True),
    )

    return BenchmarkQuestion(
        id=row.id,
        text=row.text,
        question_type=row.question_type,
        references=row.references or [],
        attributes=attributes,
    )


@router.post("/run-tests")
async def run_tests(request: RunTestsRequest) -> dict:
    """Run benchmark tests against the RAG system.

    Flow:
        1. Load benchmark set and verify it exists
        2. Load questions and convert to BenchmarkQuestion objects
        3. Create TestRunner with MetricsController and ContextFetcher
        4. Run tests (RAG calls + metric computation)
        5. Save test run and results to the database
        6. Return test run with results and average metrics
    """
    settings = get_settings()

    # 1-2. Load benchmark set + questions
    try:
        with get_session() as session:
            benchmark_set = crud.get_benchmark_set(
                session,
                request.benchmark_set_id,
                request.workspace_id,
            )
            if benchmark_set is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Benchmark set {request.benchmark_set_id} not found",
                )

            question_rows = crud.get_benchmark_questions(session, request.benchmark_set_id)
            if not question_rows:
                raise HTTPException(
                    status_code=400,
                    detail="Benchmark set has no questions",
                )

            questions = [_row_to_benchmark_question(r) for r in question_rows]

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to load benchmark set: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load benchmark set") from exc

    # 3. Create services
    try:
        context_fetcher = ContextFetcher.from_settings(settings)
        metrics_controller = MetricsController.from_settings(settings)
        runner = TestRunner(metrics_controller, context_fetcher)
    except Exception as exc:
        logger.error("Failed to initialize test services: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to initialize test services") from exc

    # 4. Run tests
    try:
        run_result = await runner.run_tests(questions, request.workspace_id)
    except Exception as exc:
        logger.error("Test execution failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Test execution failed") from exc

    # 5. Save test run + results to DB
    try:
        contexts = run_result["contexts"]
        metrics_results = run_result["metrics_results"]
        avg_metrics = run_result["avg_metrics"]

        with get_session() as session:
            test_run = crud.create_test_run(
                session,
                benchmark_set_id=request.benchmark_set_id,
                name=request.name,
                description=request.description,
                total_tests=len(questions),
                **avg_metrics,
            )

            result_dicts = []
            for ctx, mr in zip(contexts, metrics_results):
                result_dicts.append(
                    {
                        "question": ctx.question.model_dump(),
                        "actual_answer": ctx.answer,
                        "correctness": mr.correctness,
                        "answer_relevancy": mr.answer_relevancy,
                        "faithfulness": mr.faithfulness,
                        "context_precision": mr.context_precision,
                        "context_recall": mr.context_recall,
                        "confidence": mr.confidence,
                        "ndcg_at_10": mr.ndcg_at_10,
                        "mrr": mr.mrr,
                        "precision_at_k": mr.precision_at_k,
                        "claim_scores": mr.claim_scores,
                        "context": ctx.to_dict(),
                    }
                )

            test_result_rows = crud.create_test_results(session, test_run.id, result_dicts)

            response = {
                "id": test_run.id,
                "benchmark_set_id": test_run.benchmark_set_id,
                "name": test_run.name,
                "description": test_run.description,
                "total_tests": test_run.total_tests,
                "created_at": test_run.created_at.isoformat(),
                "avg_correctness": test_run.avg_correctness,
                "avg_answer_relevancy": test_run.avg_answer_relevancy,
                "avg_faithfulness": test_run.avg_faithfulness,
                "avg_context_precision": test_run.avg_context_precision,
                "avg_context_recall": test_run.avg_context_recall,
                "avg_confidence": test_run.avg_confidence,
                "avg_ndcg_at_10": test_run.avg_ndcg_at_10,
                "avg_mrr": test_run.avg_mrr,
                "avg_precision_at_k": test_run.avg_precision_at_k,
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
                        "ndcg_at_10": tr.ndcg_at_10,
                        "mrr": tr.mrr,
                        "precision_at_k": tr.precision_at_k,
                        "claim_scores": tr.claim_scores,
                    }
                    for tr in test_result_rows
                ],
            }

    except Exception as exc:
        logger.error("Failed to save test results: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save test results") from exc

    logger.info(
        "Test run completed: id=%s, tests=%d",
        response["id"],
        response["total_tests"],
    )
    return response
