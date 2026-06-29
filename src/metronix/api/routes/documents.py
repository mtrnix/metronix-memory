"""Document management API — /api/v1/documents."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}/history")
async def get_document_history(
    document_id: str,
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    """Get version history for a document.

    Returns paginated list of versions (newest first) with metadata about
    what changed between versions.

    Args:
        document_id: Document ID to fetch history for.
        request: FastAPI request object to access app state.
        limit: Max versions to return (1-100, default 10).
        offset: Pagination offset (default 0).

    Returns:
        Dict with document_id, versions list, total count, and pagination info.

    Raises:
        HTTPException: If document not found or query fails.
    """
    logger.info(
        "api.documents.history",
        document_id=document_id,
        limit=limit,
        offset=offset,
    )

    try:
        postgres = request.app.state.postgres

        versions, total = await postgres.get_document_history(
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

        logger.info(
            "api.documents.history.ok",
            document_id=document_id,
            version_count=len(versions),
        )

        return {
            "document_id": document_id,
            "versions": [
                {
                    "version_number": v.version_number,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "sync_source": v.sync_source,
                    "changed_fields": v.changed_fields,
                    "content_preview": (
                        v.content[:200] + "..." if len(v.content) > 200 else v.content
                    ),
                }
                for v in versions
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total,
        }
    except AttributeError:
        logger.debug("api.documents.history.no_store")
        raise HTTPException(
            status_code=503,
            detail="Document versioning service not available",
        ) from None
    except Exception as exc:
        logger.error(
            "api.documents.history.error",
            document_id=document_id,
            error=str(exc),
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve document history",
        ) from exc
