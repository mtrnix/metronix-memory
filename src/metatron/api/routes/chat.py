"""Chat and upload API — /api/v1/chat, /api/v1/chat/stream, and /api/v1/upload.

Migrated from PoC metatron/api.py (the core Q&A endpoints).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from typing import AsyncGenerator, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

logger = structlog.get_logger()

router = APIRouter(tags=["chat"])

# In-memory conversation history
_conversation_history: dict[str, list[dict[str, str]]] = {}
_history_lock = threading.Lock()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    workspace_id: Optional[str] = None
    user_id: str = "user"
    top_k: int = Field(25, ge=1, le=50)
    history_turns: int = Field(6, ge=0, le=20)


class ChatResponse(BaseModel):
    answer: str
    workspace_id: str


class UploadResponse(BaseModel):
    status: str
    file_name: str
    chunks: int
    workspace_id: str
    graph_extracted: bool = True


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Hybrid search with conversation history and workspace isolation."""
    from metatron.workspaces import get_workspace_manager

    manager = get_workspace_manager()
    if req.workspace_id:
        workspace_id = req.workspace_id
    else:
        workspace = manager.get_active_workspace(req.user_id)
        workspace_id = workspace.workspace_id

    with _history_lock:
        history = _conversation_history.get(req.user_id, [])[-req.history_turns:]

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

    try:
        from metatron.retrieval.search import hybrid_search_and_answer
        answer = hybrid_search_and_answer(
            query=composite_query,
            user_id=req.user_id,
            workspace_id=req.workspace_id,
            k=req.top_k,
            intent_query=req.question,
            plugin_manager=plugin_manager,
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

    return ChatResponse(answer=answer, workspace_id=workspace_id)


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks for progressive SSE streaming."""
    parts = re.split(r'(?<=[.!?])\s+', text)
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
        history = _conversation_history.get(req.user_id, [])[-req.history_turns:]

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

        try:
            from metatron.retrieval.search import hybrid_search_and_answer
            _pm = plugin_manager  # capture for closure
            task = asyncio.get_event_loop().run_in_executor(
                None,
                lambda _pm=_pm: hybrid_search_and_answer(
                    query=composite_query,
                    user_id=req.user_id,
                    workspace_id=workspace_id,
                    k=req.top_k,
                    intent_query=req.question,
                    plugin_manager=_pm,
                ),
            )
            # Send heartbeat every 5s while search is running
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
            answer: str = task.result()
        except Exception as exc:
            logger.error("chat.stream.error", error=str(exc), exc_info=True)
            yield {"event": "error", "data": json.dumps(
                {"error": "Search failed. Please try again."},
            )}
            yield {"event": "done", "data": "{}"}
            return

        # Record history (same as non-streaming endpoint)
        with _history_lock:
            hist = _conversation_history.setdefault(req.user_id, [])
            hist.append({"user": req.question, "assistant": answer[:2000]})
            if len(hist) > 20:
                del hist[:-20]

        body, sources = extract_sources_section(answer)

        yield {"event": "status", "data": json.dumps({"status": "answering"})}

        for chunk in split_into_sentences(body):
            yield {"event": "chunk", "data": json.dumps({"text": chunk})}
            await asyncio.sleep(0.03)

        if sources:
            yield {"event": "sources", "data": json.dumps({"sources": sources})}

        yield {"event": "done", "data": json.dumps({"workspace_id": workspace_id})}

    return EventSourceResponse(_event_generator())


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form("user"),
    workspace_id: Optional[str] = Form(None),
    extract_graph: bool = Form(True),
) -> UploadResponse:
    """Upload and index a document to a workspace."""
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="No file content provided")

    file_name = file.filename or "document.txt"

    # Persist original file for later download
    from metatron.core.config import get_settings
    from metatron.storage.file_store import FileStore
    file_id = uuid4().hex
    settings = get_settings()
    file_store = FileStore(settings.file_store_path)
    try:
        await file_store.save(
            workspace_id=workspace_id or "default",
            file_id=file_id,
            filename=file_name,
            content=raw_bytes,
        )
    except Exception as exc:
        logger.warning("upload.file_persist_failed", error=str(exc))
        file_id = ""

    try:
        from metatron.ingestion.processors import is_tabular_file, process_tabular_file
        from metatron.ingestion.processors.html import process_html
        from metatron.ingestion.processors.titles import extract_title_from_markdown

        if file_name.lower().endswith(".pdf"):
            from metatron.ingestion.processors.pdf import extract_text_from_pdf
            text = extract_text_from_pdf(raw_bytes, file_name)
        elif file_name.lower().endswith(".docx"):
            from metatron.ingestion.processors.office import extract_text_from_docx
            text = extract_text_from_docx(raw_bytes)
        elif is_tabular_file(file_name):
            text, _meta = process_tabular_file(raw_bytes, file_name)
        elif file_name.lower().endswith((".html", ".htm")):
            text = raw_bytes.decode("utf-8", errors="replace")
            text = process_html(text)
            file_name = extract_title_from_markdown(text, raw_bytes) or file_name
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("upload.parse_error", file=file_name, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to parse file")

    try:
        result = _ingest_text(
            text=text,
            file_name=file_name,
            user_id=user_id,
            workspace_id=workspace_id,
            extract_graph=extract_graph,
            file_id=file_id,
        )
    except Exception as exc:
        logger.error("upload.ingest_error", file=file_name, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to index document. Please try again.",
        ) from exc

    return UploadResponse(status="ok", file_name=file_name, **result)


def _ingest_text(
    text: str,
    file_name: str,
    user_id: str = "user",
    workspace_id: str | None = None,
    extract_graph: bool = True,
    file_id: str = "",
) -> dict:
    """Send text to workspace-specific Qdrant + optionally graph."""
    from metatron.core.utils import build_doc_label
    from metatron.ingestion.chunking import chunk_text
    from metatron.ingestion.processors.dates import extract_date_from_text
    from metatron.workspaces import get_workspace_manager

    manager = get_workspace_manager()
    if workspace_id is None:
        workspace = manager.get_active_workspace(user_id)
        workspace_id = workspace.workspace_id
    else:
        workspace = manager.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace '{workspace_id}' not found")

    if not text.strip():
        raise ValueError("Document is empty")

    from metatron.storage.qdrant import get_hybrid_store
    store = get_hybrid_store(workspace_id)

    doc_date = extract_date_from_text(file_name) or extract_date_from_text(text[:500])
    doc_label, upload_time = build_doc_label(
        source_id=file_name, user_id=user_id, workspace_id=workspace_id,
    )

    metadata = {
        "title": file_name,
        "type": "upload",
        "workspace_id": workspace_id,
        "user_id": user_id,
        "doc_label": doc_label,
        "url": f"/api/v1/files/{file_id}/download?workspace_id={workspace_id}" if file_id and workspace_id else "",
    }
    if doc_date:
        metadata["date"] = doc_date

    chunks = chunk_text(text, max_chars=2500, overlap=200)
    for chunk in chunks:
        store.add_document(text=chunk, metadata=metadata, doc_id=doc_label)

    if extract_graph:
        from metatron.storage.memgraph import write_doc_graph_to_memgraph
        graph_text = chunks[0] if len(text) > 8000 else text
        write_doc_graph_to_memgraph(
            text=graph_text,
            file_name=file_name,
            user_id=user_id,
            workspace_id=workspace_id,
            doc_label=doc_label,
            upload_time=upload_time,
            metadata=metadata,
        )

    return {"chunks": len(chunks), "workspace_id": workspace_id, "graph_extracted": extract_graph}
