"""Chat and upload API — /api/v1/chat, /api/v1/chat/stream, and /api/v1/upload.

Migrated from PoC metatron/api.py (the core Q&A endpoints).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import AsyncGenerator
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from metatron.api.dependencies import build_telemetry_context_cm, resolve_workspace_id
from metatron.auth.dependencies import require_editor
from metatron.core.models import User  # noqa: TC001 — Annotated[User, Depends()] is runtime
from metatron.retrieval.trace import append_trace_footer, maybe_create_trace

logger = structlog.get_logger()

router = APIRouter(tags=["chat"])

# In-memory conversation history
_conversation_history: dict[str, list[dict[str, str]]] = {}
_history_lock = threading.Lock()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    workspace_id: str | None = None
    user_id: str = "user"
    top_k: int = Field(25, ge=1, le=50)
    history_turns: int = Field(6, ge=0, le=20)


class ChatResponse(BaseModel):
    answer: str
    workspace_id: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Hybrid search with conversation history and workspace isolation."""
    from metatron.workspaces import get_workspace_manager

    manager = get_workspace_manager()
    if req.workspace_id:
        workspace_id = req.workspace_id
    else:
        workspace = manager.get_active_workspace(req.user_id)
        workspace_id = workspace.workspace_id

    with _history_lock:
        history = _conversation_history.get(req.user_id, [])[-req.history_turns :]

    MAX_HISTORY_CHARS = 4000
    history_lines = []
    total_chars = 0
    for turn in reversed(history):
        user_msg = turn.get("user", "")[:500]
        line = f"Previous question: {user_msg}"
        if total_chars + len(line) > MAX_HISTORY_CHARS:
            break
        history_lines.insert(0, line)
        total_chars += len(line)

    composite_query = (
        "\n".join(history_lines + [f"Current question: {req.question}"])
        if history_lines
        else req.question
    )

    plugin_manager = getattr(request.app.state, "plugin_manager", None)

    with build_telemetry_context_cm(request, source="rest") as tctx:
        rag_trace = maybe_create_trace(
            tctx, raw_user_message=req.question, composite_query=composite_query
        )
        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            answer = await hybrid_search_and_answer(
                query=composite_query,
                user_id=req.user_id,
                workspace_id=req.workspace_id,
                k=req.top_k,
                intent_query=req.question,
                plugin_manager=plugin_manager,
                source="rest",
                rag_trace=rag_trace,
            )
        except Exception as exc:
            logger.error("chat.error", error=str(exc), exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Search failed. Please try again.",
            ) from exc

    with _history_lock:
        hist = _conversation_history.setdefault(req.user_id, [])
        hist.append({"user": req.question, "assistant": answer[:2000]})
        if len(hist) > 20:
            del hist[:-20]
        if len(_conversation_history) > 100:
            oldest = list(_conversation_history.keys())[:50]
            for uid in oldest:
                del _conversation_history[uid]

    answer = append_trace_footer(
        answer, rag_trace, enabled=request.app.state.settings.rag_trace_footer_enabled
    )

    return ChatResponse(answer=answer, workspace_id=workspace_id)


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks for progressive SSE streaming."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for part in parts:
        current += (" " if current else "") + part
        if len(current) > 80:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


def extract_sources_section(answer: str) -> tuple[str, list[str]]:
    """Split answer into body and source lines."""
    marker = "\U0001f4da Sources:"
    if marker not in answer:
        return answer, []
    body, _, sources_block = answer.partition(marker)
    sources = [line.strip() for line in sources_block.strip().splitlines() if line.strip()]
    return body.strip(), sources


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> EventSourceResponse:
    """Stream chat response via Server-Sent Events.

    Events:
    - ``status`` — search phase indicator (``searching``, ``answering``)
    - ``chunk``  — incremental answer text
    - ``sources`` — source citations array
    - ``done``   — signals end of stream
    """
    from metatron.workspaces import get_workspace_manager

    manager = get_workspace_manager()
    if req.workspace_id:
        workspace_id = req.workspace_id
    else:
        workspace = manager.get_active_workspace(req.user_id)
        workspace_id = workspace.workspace_id

    with _history_lock:
        history = _conversation_history.get(req.user_id, [])[-req.history_turns :]

    MAX_HISTORY_CHARS = 4000
    history_lines: list[str] = []
    total_chars = 0
    for turn in reversed(history):
        user_msg = turn.get("user", "")[:500]
        line = f"Previous question: {user_msg}"
        if total_chars + len(line) > MAX_HISTORY_CHARS:
            break
        history_lines.insert(0, line)
        total_chars += len(line)

    composite_query = (
        "\n".join(history_lines + [f"Current question: {req.question}"])
        if history_lines
        else req.question
    )

    async def _event_generator() -> AsyncGenerator[dict[str, str], None]:
        yield {"event": "status", "data": json.dumps({"status": "searching"})}

        plugin_manager = getattr(request.app.state, "plugin_manager", None)

        with build_telemetry_context_cm(request, source="rest") as tctx:
            rag_trace = maybe_create_trace(
                tctx, raw_user_message=req.question, composite_query=composite_query
            )
            try:
                from metatron.retrieval.search import hybrid_search_and_answer

                answer: str = await hybrid_search_and_answer(
                    query=composite_query,
                    user_id=req.user_id,
                    workspace_id=workspace_id,
                    k=req.top_k,
                    intent_query=req.question,
                    plugin_manager=plugin_manager,
                    source="rest",
                    rag_trace=rag_trace,
                )
            except Exception as exc:
                logger.error("chat.stream.error", error=str(exc), exc_info=True)
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"error": "Search failed. Please try again."},
                    ),
                }
                yield {"event": "done", "data": "{}"}
                return

        # Record history (same as non-streaming endpoint)
        with _history_lock:
            hist = _conversation_history.setdefault(req.user_id, [])
            hist.append({"user": req.question, "assistant": answer[:2000]})
            if len(hist) > 20:
                del hist[:-20]

        body, sources = extract_sources_section(answer)
        body = append_trace_footer(
            body, rag_trace, enabled=request.app.state.settings.rag_trace_footer_enabled
        )

        yield {"event": "status", "data": json.dumps({"status": "answering"})}

        for chunk in split_into_sentences(body):
            yield {"event": "chunk", "data": json.dumps({"text": chunk})}
            await asyncio.sleep(0.03)

        if sources:
            yield {"event": "sources", "data": json.dumps({"sources": sources})}

        yield {"event": "done", "data": json.dumps({"workspace_id": workspace_id})}

    return EventSourceResponse(_event_generator())


@router.post("/upload")
async def upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_editor)],
    file: UploadFile = File(...),
) -> JSONResponse:
    """Backward-compatible single-file upload. Delegates to the files pipeline.

    No longer persists the original file to disk and no longer returns a download
    URL; ``extract_graph`` is ignored (graph extraction always runs in the
    background, like connectors).

    Workspace is resolved solely via JWT / access-checked ``?workspace_id`` query
    param (same as ``/api/v1/files/``).  Caller-supplied form fields cannot
    override workspace isolation.
    """
    from metatron.api.routes.files import _ingest_uploads

    ws = resolve_workspace_id(request)
    user_id = getattr(user, "id", "user")
    raw_bytes = await file.read()
    report = await _ingest_uploads(
        ws, user_id, [(file.filename or "document.txt", raw_bytes)], background_tasks
    )
    status_code = 207 if report["skipped"] > 0 else 200
    return JSONResponse(status_code=status_code, content=report)
