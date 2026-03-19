"""Benchmark generation API — POST /generate.

Accepts a GenerateRequest with a connection_id, samples documents from
the connection's source via connectors, generates benchmark questions
through BenchmarkQED, saves the benchmark set to the database, and
returns the result.
"""

from __future__ import annotations

import structlog

from fastapi import APIRouter, HTTPException

from metatron.benchmarker.db import crud
from metatron.benchmarker.schemas.benchmark import GenerateRequest
from metatron.benchmarker.services.document_sampler import DocumentSampler
from metatron.benchmarker.services.generator import BenchmarkGenerator
from metatron.connectors.registry import ConnectorRegistry, register_builtins
from metatron.core.config import get_settings
from metatron.core.models import Connection
from metatron.storage.pg_connection import get_session
from metatron.storage.postgres import PostgresStore

logger = structlog.get_logger()

router = APIRouter(tags=["benchmarker-generation"])


@router.post("/generate")
async def generate_benchmark(request: GenerateRequest) -> dict:
    """Generate a benchmark set from workspace documents.

    Flow:
        1. Load connection from DB and decrypt config
        2. Sample documents via DocumentSampler + connector
        3. Generate questions via BenchmarkGenerator (BenchmarkQED)
        4. Save benchmark set and questions to the database
        5. Return the benchmark set with questions
    """
    settings = get_settings()

    if not settings.fernet_key:
        raise HTTPException(
            status_code=500,
            detail="FERNET_KEY not configured",
        )

    # 1. Load connection from DB
    connection_id = request.connection_id

    store = PostgresStore(settings.postgres_dsn)
    try:
        conn = await store.get_connection_decrypted(
            connection_id, settings.fernet_key,
        )
    finally:
        await store.close()

    if not conn:
        raise HTTPException(
            status_code=404,
            detail=f"Connection {connection_id} not found",
        )

    connector_type = conn["connector_type"]
    decrypted_config = conn["config"]
    connection = Connection(
        id=conn["id"],
        workspace_id=conn["workspace_id"],
        connector_type=connector_type,
    )

    # 2. Sample documents
    try:
        registry = ConnectorRegistry()
        register_builtins(registry)
        sampler = DocumentSampler(registry)

        oversample_count = request.num_questions * 5
        documents = await sampler.sample_documents(
            connection, decrypted_config,
            request.workspace_id, oversample_count,
        )

        if not documents:
            raise ValueError(
                "No documents found for the specified source",
            )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Document sampling failed: %s", exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Document sampling failed",
        ) from exc

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
        logger.error(
            "Question generation failed: %s", exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Question generation failed",
        ) from exc

    # 4. Save to database
    try:
        with get_session() as session:
            benchmark_set = crud.create_benchmark_set(
                session,
                workspace_id=request.workspace_id,
                connection_id=request.connection_id,
                name=f"Generated ({connector_type})",
                description=(
                    f"Auto-generated from {connector_type} documents"
                ),
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
            crud.create_benchmark_questions(
                session, benchmark_set.id, question_dicts,
            )

            result = {
                "id": benchmark_set.id,
                "workspace_id": benchmark_set.workspace_id,
                "connection_id": benchmark_set.connection_id,
                "name": benchmark_set.name,
                "description": benchmark_set.description,
                "tokens_used": benchmark_set.tokens_used,
                "question_count": benchmark_set.question_count,
                "created_at": benchmark_set.created_at.isoformat(),
                "questions": [q.model_dump() for q in questions],
            }

    except Exception as exc:
        logger.error(
            "Failed to save benchmark set: %s", exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to save benchmark set",
        ) from exc

    logger.info(
        "Benchmark generated: id=%s, questions=%d, tokens=%d",
        result["id"],
        len(questions),
        tokens_used,
    )
    return result
