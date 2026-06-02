"""POST /v1/proxy/chat/completions — proxy LLM surface (MTRNIX-372)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from metatron.activity.context import current_agent_id
from metatron.agents.service import AgentNotFoundError
from metatron.api.dependencies import resolve_workspace_id
from metatron.api.routes.openai_compat import verify_openai_compat_key
from metatron.proxy.service import AgentUpstreamNotConfiguredError

if TYPE_CHECKING:
    from metatron.proxy.service import ProxyService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/proxy", tags=["proxy"])


class ProxyChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    stream: bool = True


def get_proxy_service(request: Request) -> ProxyService:
    """Build a per-workspace ProxyService from app.state."""
    builder = getattr(request.app.state, "proxy_service_builder", None)
    if builder is None:
        raise HTTPException(status_code=503, detail="proxy not configured")
    workspace_id = resolve_workspace_id(request)
    return builder(workspace_id)


@router.post("/chat/completions", dependencies=[Depends(verify_openai_compat_key)])
async def proxy_chat_completions(
    req: ProxyChatRequest,
    request: Request,
) -> Any:
    settings = request.app.state.settings
    if not settings.proxy_enabled:
        raise HTTPException(status_code=404, detail="proxy disabled")

    agent_id = current_agent_id.get()
    if not agent_id:
        raise HTTPException(status_code=400, detail="x_agent_id_required")

    workspace_id = resolve_workspace_id(request)
    service = get_proxy_service(request)
    try:
        return await service.dispatch(
            agent_id=agent_id,
            workspace_id=workspace_id,
            request_body=req.model_dump(),
            mode="proxy",
        )
    except AgentUpstreamNotConfiguredError as exc:
        raise HTTPException(
            status_code=400, detail="agent_upstream_not_configured"
        ) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
