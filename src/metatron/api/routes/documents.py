"""Document management API — /api/v1/documents."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}/history")
async def get_document_history(
    document_id: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    request: Request = None,
) -> dict[str, object]:
    """Get version history for a document.

    Returns paginated list of versions (newest first) with metadata about
    what changed between versions.

    Args:
        document_id: Document ID to fetch history for.
        limit: Max versions to return (1-100, default 10).
        offset: Pagination offset (default 0).
        request: FastAPI request object to access app state.

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

    try:
        # Get postgres store from app state
        postgres = request.app.state.postgres
        
        # Call storage layer
        versions, total = await postgres.get_document_history(
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
        
        logger.info(
            "document_history_endpoint_success",
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
                    "content_preview": v.content[:200] + "..." if len(v.content) > 200 else v.content,
                }
                for v in versions
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total,
        }
    except AttributeError:
        # postgres store not initialized
        logger.debug("postgres_store_not_initialized_in_app_state")
        raise HTTPException(
            status_code=503,
            detail="Document versioning service not available",
        )
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
