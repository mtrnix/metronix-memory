"""Files API — upload + folder import into the connector ingestion pipeline.

/api/v1/files. Uploaded files are parsed to text and ingested exactly like
connector documents: PostgreSQL raw_documents (sync) -> Qdrant + Neo4j (background).
Original binaries are NOT persisted.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, UploadFile
from fastapi.responses import JSONResponse

from metatron.api.dependencies import resolve_workspace_id
from metatron.auth.dependencies import require_editor
from metatron.core.config import get_settings
from metatron.core.models import (  # noqa: TC001 — Annotated[User, Depends()] is runtime
    Document,
    User,
)
from metatron.ingestion.sync import persist_raw_documents, sync_documents_to_stores
from metatron.ingestion.upload import (
    build_upload_document,
    is_allowed_upload,
    parse_upload,
)
from metatron.storage.postgres import PostgresStore

logger = structlog.get_logger()

router = APIRouter(prefix="/files", tags=["files"])


async def _ingest_uploads(
    workspace_id: str,
    user_id: str,
    files: list[tuple[str, bytes]],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Validate, parse, persist (sync), and schedule background indexing.

    ``files`` is a list of (filename, raw_bytes). Returns the per-file report.
    """
    results: list[dict[str, Any]] = []
    docs: list[Document] = []
    for filename, raw_bytes in files:
        if not is_allowed_upload(filename):
            ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
            results.append({
                "filename": filename,
                "status": "skipped_format",
                "source_id": None,
                "reason": f"extension {ext} not allowed",
            })
            continue
        try:
            text = parse_upload(filename, raw_bytes)
        except Exception as exc:  # noqa: BLE001 - per-file isolation by design
            results.append({
                "filename": filename,
                "status": "failed",
                "source_id": None,
                "reason": str(exc),
            })
            continue
        if not text.strip():
            results.append({
                "filename": filename,
                "status": "skipped_empty",
                "source_id": None,
                "reason": "no extractable text",
            })
            continue
        docs.append(build_upload_document(filename, text, user_id, workspace_id))
        results.append({
            "filename": filename,
            "status": "accepted",
            "source_id": filename,
            "reason": None,
        })

    settings = get_settings()
    if docs:
        store = PostgresStore(settings.postgres_dsn)
        await persist_raw_documents(store, workspace_id, "upload", None, docs)
        background_tasks.add_task(_background_sync, workspace_id, docs)

    accepted = sum(1 for r in results if r["status"] == "accepted")
    return {
        "workspace_id": workspace_id,
        "accepted": accepted,
        "skipped": len(results) - accepted,
        "results": results,
    }


async def _background_sync(workspace_id: str, docs: list[Document]) -> None:
    """Background task: Qdrant + graph ingestion with a fresh PG store."""
    settings = get_settings()
    store = PostgresStore(settings.postgres_dsn)
    try:
        await sync_documents_to_stores(
            store,
            workspace_id,
            "upload",
            docs,
            source_role="user_upload",
            incremental=True,
        )
    except Exception as exc:  # noqa: BLE001 - background best-effort
        logger.warning("upload.background_sync.error", error=str(exc))


@router.post("/")
async def upload_files(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile],
    user: Annotated[User, Depends(require_editor)],
) -> JSONResponse:
    """Upload one or more files (multipart) into the workspace knowledge base."""
    workspace_id = resolve_workspace_id(request)
    user_id = getattr(user, "id", "user")
    payload = [(f.filename or "upload.bin", await f.read()) for f in files]
    report = await _ingest_uploads(workspace_id, user_id, payload, background_tasks)
    status_code = 207 if report["skipped"] > 0 else 200
    return JSONResponse(status_code=status_code, content=report)
