"""Document management API — /api/v1/documents."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}/history")
async def get_document_history(
    document_id: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    """Get version history for a document.

    Returns paginated list of versions (newest first) with metadata about
    what changed between versions.

    Args:
        document_id: Document ID to fetch history for.
        limit: Max versions to return (1-100, default 10).
        offset: Pagination offset (default 0).

    Returns:
        Dict with document_id, versions list, total count, and pagination info.

    Raises:
        HTTPException: If document not found or query fails.
    """
    logger.info(
        "api.document.history",
        document_id=document_id,
        limit=limit,
        offset=offset,
    )

    # TODO: implement with request.app.state.postgres.get_document_history()
    # 1. Get postgres store from request context
    # 2. Call postgres.get_document_history(document_id, limit, offset)
    # 3. Format response with version details
    # 4. Handle errors gracefully

    try:
        # Placeholder: return empty until postgres methods are implemented
        return {
            "document_id": document_id,
            "versions": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
        }
    except Exception as exc:
        logger.error(
            "failed_to_get_document_history",
            document_id=document_id,
            error=str(exc),
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve document history",
        )
