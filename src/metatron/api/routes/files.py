"""Files API — upload + folder import into the connector ingestion pipeline.

/api/v1/files. Uploaded files are parsed to text and ingested exactly like
connector documents: PostgreSQL raw_documents (sync) -> Qdrant + Neo4j (background).
Original binaries are NOT persisted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from metatron.api.dependencies import resolve_workspace_id
from metatron.auth.dependencies import require_admin, require_editor
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
        try:
            await persist_raw_documents(store, workspace_id, "upload", None, docs)
        finally:
            await store.close()
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
    finally:
        await store.close()


class ImportPathRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    path: str
    recursive: bool = False


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


@router.post("/import-path")
async def import_path(
    request: Request,
    background_tasks: BackgroundTasks,
    body: ImportPathRequest,
    user: Annotated[User, Depends(require_admin)],
) -> JSONResponse:
    """Ingest all files under a server-side directory path (admin only)."""
    workspace_id = resolve_workspace_id(request)
    user_id = getattr(user, "id", "user")

    root = Path(body.path).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    walker = root.rglob("*") if body.recursive else root.glob("*")
    payload: list[tuple[str, bytes]] = []
    for entry in walker:
        if not entry.is_file():
            continue
        try:
            payload.append((entry.name, entry.read_bytes()))
        except Exception as exc:  # noqa: BLE001 - per-file isolation
            logger.warning("import_path.read_error", file=str(entry), error=str(exc))

    report = await _ingest_uploads(workspace_id, user_id, payload, background_tasks)
    status_code = 207 if report["skipped"] > 0 else 200
    return JSONResponse(status_code=status_code, content=report)
