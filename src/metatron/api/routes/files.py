"""Files API — upload, list, verify integrity, download. /api/v1/files."""

from __future__ import annotations

import mimetypes
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from metatron.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter(prefix="/files", tags=["files"])


class FileRecordResponse(BaseModel):
    """Response body for a file record."""

    model_config = ConfigDict(strict=True)

    id: str
    workspace_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_at: str


@router.post("/", status_code=201)
async def upload_file(workspace_id: str, file: UploadFile) -> FileRecordResponse:
    """Upload a file to a workspace.

    Stores the file on disk, computes SHA-256, and creates
    a metadata record in PostgreSQL.
    """
    logger.info(
        "api.files.upload",
        workspace_id=workspace_id,
        filename=file.filename,
    )
    # TODO: implement
    # 1. Read file content
    # 2. Save via FileStore.save()
    # 3. Create FileRecord in postgres
    # 4. Return FileRecordResponse
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/")
async def list_files(workspace_id: str) -> list[FileRecordResponse]:
    """List all files in a workspace."""
    logger.info("api.files.list", workspace_id=workspace_id)
    # TODO: implement
    return []


@router.get("/{file_id}/verify")
async def verify_file(file_id: str) -> dict[str, str]:
    """Verify file integrity by comparing stored and computed SHA-256.

    Returns {"status": "ok"} if checksums match, error otherwise.
    """
    logger.info("api.files.verify", file_id=file_id)
    # TODO: implement
    # 1. Fetch FileRecord from postgres
    # 2. Read file from FileStore
    # 3. Compare sha256 (FileStore.read does this)
    # 4. Return status
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{file_id}/download")
async def download_file(file_id: str, workspace_id: str) -> FileResponse:
    """Download an uploaded file by ID.

    Locates the file on disk by scanning the workspace directory for
    a file starting with ``{file_id}_``. Returns the file with
    appropriate Content-Type and Content-Disposition headers.
    """
    settings = get_settings()
    base = Path(settings.file_store_path).resolve()
    ws_dir = (base / workspace_id).resolve()
    if not ws_dir.is_relative_to(base) or not ws_dir.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    matches = [f for f in ws_dir.iterdir() if f.name.startswith(f"{file_id}_")]
    if not matches:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = matches[0]
    original_name = file_path.name[len(file_id) + 1:]
    content_type, _ = mimetypes.guess_type(original_name)
    content_type = content_type or "application/octet-stream"

    return FileResponse(
        path=file_path,
        media_type=content_type,
        filename=original_name,
    )
