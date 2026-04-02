"""Application config endpoint — /api/v1/config."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["config"])


@router.get("/config")
def get_config(request: Request) -> dict:
    """Return application configuration including installed plugins.

    Public endpoint (no auth required). Used by UI to detect
    enterprise features.
    """
    plugins: list[str] = []
    pm = getattr(request.app.state, "plugin_manager", None)
    if pm:
        plugins = pm.loaded_plugins
    return {"plugins": plugins}
