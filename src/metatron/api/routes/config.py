"""Application config endpoint — /api/v1/config."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(tags=["config"])


@router.get("/config")
def get_config(request: Request) -> dict:
    """Return application configuration including installed plugins.

    Public endpoint (no auth required). Used by UI to detect
    enterprise features and their enabled state.
    """
    plugins: list[str] = []
    pm = getattr(request.app.state, "plugin_manager", None)
    if pm:
        plugins = pm.loaded_plugins

    # enterprise_enabled: None if not installed, True/False if installed
    enterprise_enabled = None
    if "enterprise" in plugins:
        enterprise_enabled = getattr(request.app.state, "enterprise_enabled", True)

    return {
        "plugins": plugins,
        "enterprise_enabled": enterprise_enabled,
    }


class EnterpriseToggleRequest(BaseModel):
    enabled: bool


@router.put("/config/enterprise")
def toggle_enterprise(req: EnterpriseToggleRequest, request: Request) -> dict:
    """Enable or disable enterprise features at runtime.

    Admin-only. Only works if enterprise plugin is installed.
    Does not unload the plugin — just hides enterprise features from UI
    and disables enterprise middleware/hooks.
    """
    user = getattr(request.state, "user", {})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    pm = getattr(request.app.state, "plugin_manager", None)
    if not pm or "enterprise" not in pm.loaded_plugins:
        raise HTTPException(status_code=404, detail="Enterprise plugin not installed")

    request.app.state.enterprise_enabled = req.enabled
    logger.info("config.enterprise.toggled", enabled=req.enabled)

    return {"enterprise_enabled": req.enabled}
