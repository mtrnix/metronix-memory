"""Dashboard API routes."""

from fastapi import APIRouter

from .graph import router as graph_router
from .overview import router as overview_router
from .sync import router as sync_router

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Include sub-routers
router.include_router(overview_router)
router.include_router(sync_router)
router.include_router(graph_router)

__all__ = ["router"]
