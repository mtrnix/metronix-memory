"""Files API — upload, list, verify integrity. /api/v1/files."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

logger = structlog.get_logger()

router = APIRouter(prefix="/files", tags=["files"])


class FileResponse(BaseModel):
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
async def upload_file(workspace_id: str, file: UploadFile) -> FileResponse:
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
    # 4. Return FileResponse
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/")
async def list_files(workspace_id: str) -> list[FileResponse]:
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
