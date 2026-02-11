"""Chat and upload API — /api/v1/chat and /api/v1/upload.

Migrated from PoC metatron/api.py (the core Q&A endpoints).
"""

from __future__ import annotations

import threading
from typing import Optional

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = structlog.get_logger()

router = APIRouter(tags=["chat"])

# In-memory conversation history
_conversation_history: dict[str, list[dict[str, str]]] = {}
_history_lock = threading.Lock()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    workspace_id: Optional[str] = None
    user_id: str = "user"
    top_k: int = Field(5, ge=1, le=20)
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
def chat(req: ChatRequest) -> ChatResponse:
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

    try:
        from metatron.retrieval.search import hybrid_search_and_answer
        answer = hybrid_search_and_answer(
            query=composite_query,
            user_id=req.user_id,
            workspace_id=req.workspace_id,
            k=req.top_k,
            intent_query=req.question,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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

    try:
        from metatron.ingestion.processors import is_tabular_file, process_tabular_file
        from metatron.ingestion.processors.html import process_html
        from metatron.ingestion.processors.titles import extract_title_from_markdown

        if is_tabular_file(file_name):
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
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {e}")

    try:
        result = _ingest_text(
            text=text,
            file_name=file_name,
            user_id=user_id,
            workspace_id=workspace_id,
            extract_graph=extract_graph,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return UploadResponse(status="ok", file_name=file_name, **result)


def _ingest_text(
    text: str,
    file_name: str,
    user_id: str = "user",
    workspace_id: str | None = None,
    extract_graph: bool = True,
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
    chunks = chunk_text(text, max_chars=2500, overlap=200)

    doc_date = extract_date_from_text(file_name) or extract_date_from_text(text[:500])
    doc_label, upload_time = build_doc_label(
        source_id=file_name, user_id=user_id, workspace_id=workspace_id,
    )

    metadata = {
        "title": file_name,
        "type": "confluence",
        "workspace_id": workspace_id,
        "user_id": user_id,
        "doc_label": doc_label,
    }
    if doc_date:
        metadata["date"] = doc_date

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
        )

    return {"chunks": len(chunks), "workspace_id": workspace_id, "graph_extracted": extract_graph}
