"""Thin synchronous store for llm_generation_log rows (MTRNIX-336).

This module is intentionally minimal — one INSERT, no reads, no batching.
The export utility (scripts/export_llm_dataset.py) reads via raw SQL.

Called from metronix.llm.telemetry.emit_log() which runs inside a thread-pool
worker (asyncio.to_thread), so the insert must be synchronous. The single extra
PG round-trip per LLM call is paid in the worker thread; the event loop is
never blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from metronix.storage.pg_connection import get_session
from metronix.storage.pg_models import LLMGenerationLogRow

logger = structlog.get_logger()


@dataclass
class LLMLogRowData:
    """All fields required for a single llm_generation_log insert."""

    call_site: str
    provider: str
    model: str
    request_messages: list[dict[str, Any]]
    success: bool
    # Optional / nullable fields
    source: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    correlation_id: str | None = None  # UUID as str
    response_content: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    error_class: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


def insert_log_row_sync(row: LLMLogRowData) -> None:
    """Insert one row into llm_generation_log synchronously via psycopg2.

    Must be called from a sync context (the telemetry wrapper runs inside
    asyncio.to_thread so no event loop is running in the calling thread).

    Never raises — any exception is logged at DEBUG level and swallowed.
    Callers should additionally catch at the emit_log() level.
    """
    try:
        with get_session() as session:
            log_row = LLMGenerationLogRow(
                call_site=row.call_site,
                source=row.source,
                workspace_id=row.workspace_id,
                user_id=row.user_id,
                agent_id=row.agent_id,
                correlation_id=row.correlation_id,
                provider=row.provider,
                model=row.model,
                request_messages=row.request_messages,
                response_content=row.response_content,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.total_tokens,
                latency_ms=row.latency_ms,
                success=row.success,
                error_class=row.error_class,
                error_message=row.error_message,
                extra_metadata=row.metadata,
            )
            session.add(log_row)
    except Exception as exc:
        logger.debug(
            "llm_telemetry.store.insert_failed",
            call_site=row.call_site,
            error=str(exc),
        )
        raise
