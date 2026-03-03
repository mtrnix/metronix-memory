"""Benchmark generation API — POST /generate.

Accepts a GenerateRequest, samples documents from the specified source
via connectors, generates benchmark questions through BenchmarkQED,
saves the benchmark set to the database, and returns the result.
"""

from __future__ import annotations

import structlog

from fastapi import APIRouter, HTTPException

from metatron.benchmarker.db import crud
from metatron.benchmarker.schemas.benchmark import GenerateRequest
from metatron.benchmarker.services.document_sampler import DocumentSampler
from metatron.benchmarker.services.generator import BenchmarkGenerator
from metatron.connectors.registry import ConnectorRegistry, register_builtins
from metatron.core.config import Settings, get_settings
from metatron.core.models import Connection
from metatron.storage.pg_connection import get_session

logger = structlog.get_logger()

router = APIRouter(tags=["benchmarker-generation"])


@router.post("/generate")
async def generate_benchmark(request: GenerateRequest) -> dict:
    """Generate a benchmark set from workspace documents.

    Flow:
        1. Build connection from env config (same approach as /sync command)
        2. Sample documents via DocumentSampler + connector
        3. Generate questions via BenchmarkGenerator (BenchmarkQED)
        4. Save benchmark set and questions to the database
        5. Return the benchmark set with questions
    """
    settings = get_settings()

    # 1. Build connection from env config (same approach as /sync command)
    config = _config_from_env(request.source, settings)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No {request.source} configuration found in environment variables",
        )
    connection = Connection(
        workspace_id=request.workspace_id,
        connector_type=request.source,
    )
    decrypted_config = config

    # 2. Sample documents
    try:
        registry = ConnectorRegistry()
        register_builtins(registry)
        sampler = DocumentSampler(registry)

        oversample_count = request.num_questions * 5
        documents = await sampler.sample_documents(
            connection, decrypted_config, request.workspace_id, oversample_count,
        )

        if not documents:
            raise ValueError("No documents found for the specified source")

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Document sampling failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Document sampling failed") from exc

    # 3. Generate questions
    try:
        generator = BenchmarkGenerator.from_settings(settings)
        questions = await generator.generate_questions(
            documents, request.num_questions, request.num_clusters,
        )
        tokens_used = generator.count_tokens_used()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Question generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Question generation failed") from exc

    # 4. Save to database
    try:
        with get_session() as session:
            benchmark_set = crud.create_benchmark_set(
                session,
                workspace_id=request.workspace_id,
                name=f"Generated ({request.source})",
                source=request.source,
                description=f"Auto-generated from {request.source} documents",
                tokens_used=tokens_used,
                question_count=len(questions),
            )

            question_dicts = [
                {
                    "id": q.id,
                    "text": q.text,
                    "question_type": q.question_type,
                    "references": q.references,
                    "attributes": q.attributes.model_dump(),
                }
                for q in questions
            ]
            crud.create_benchmark_questions(session, benchmark_set.id, question_dicts)

            result = {
                "id": benchmark_set.id,
                "workspace_id": benchmark_set.workspace_id,
                "name": benchmark_set.name,
                "source": benchmark_set.source,
                "description": benchmark_set.description,
                "tokens_used": benchmark_set.tokens_used,
                "question_count": benchmark_set.question_count,
                "created_at": benchmark_set.created_at.isoformat(),
                "questions": [q.model_dump() for q in questions],
            }

    except Exception as exc:
        logger.error("Failed to save benchmark set: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save benchmark set") from exc

    logger.info(
        "Benchmark generated: id=%s, questions=%d, tokens=%d",
        result["id"],
        len(questions),
        tokens_used,
    )
    return result


def _config_from_env(connector_type: str, settings: Settings) -> dict[str, str]:
    """Build connector config dict from environment variables."""
    if connector_type == "confluence":
        if not settings.confluence_url:
            return {}
        return {
            "url": settings.confluence_url,
            "username": settings.confluence_username,
            "api_token": settings.confluence_api_token,
            "space_key": settings.confluence_space_key,
        }
    if connector_type == "jira":
        if not settings.jira_url:
            return {}
        return {
            "url": settings.jira_url,
            "username": settings.jira_username,
            "api_token": settings.jira_api_token,
            "project_key": settings.jira_project_key,
        }
    if connector_type == "notion":
        if not settings.notion_api_token:
            return {}
        return {
            "api_token": settings.notion_api_token,
        }
    return {}
