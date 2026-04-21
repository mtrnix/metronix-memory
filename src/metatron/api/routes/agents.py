"""Agent Registry REST API — /api/v1/agents.

Exposes CRUD, lifecycle transitions and config-version history for agents
in a workspace. Workspace is always derived from the authenticated user —
never accepted from body or query string.

RBAC — aligns with the ``memory/`` module convention:

* ``viewer+`` — read-only endpoints: ``GET /``, ``GET /{id}``, ``GET /{id}/versions``
* ``editor+`` — write and lifecycle: ``POST /``, ``PUT /{id}``, ``DELETE /{id}``,
  ``POST /{id}/start|stop|pause``
"""

from __future__ import annotations

import json
from datetime import datetime  # noqa: TC003 — runtime for pydantic field validation
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from metatron.agents.models import (
    AgentConfigVersion,  # noqa: TC001 — helper annotations need runtime resolution
    AgentRecord,  # noqa: TC001 — helper annotations need runtime resolution
    AgentStatus,  # noqa: TC001 — Pydantic field types need runtime resolution
)
from metatron.agents.service import (
    AgentNameConflictError,
    AgentNotFoundError,
    AgentRegistryService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)
from metatron.api.dependencies import get_agent_registry_service
from metatron.auth.dependencies import require_editor, require_viewer
from metatron.core.models import User  # noqa: TC001 — FastAPI Annotated DI needs runtime import

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Pydantic v2 schemas
# ---------------------------------------------------------------------------


_MAX_OPAQUE_BYTES = 32 * 1024  # 32 KiB serialized


def _validate_opaque_mapping(value: dict[str, Any], *, field_name: str) -> None:
    try:
        serialized = json.dumps(value)
    except (TypeError, ValueError) as exc:
        msg = f"{field_name} must be JSON-serializable"
        raise ValueError(msg) from exc
    if len(serialized) > _MAX_OPAQUE_BYTES:
        msg = f"{field_name} serialized size must not exceed 32 KiB"
        raise ValueError(msg)


class CreateAgentRequest(BaseModel):
    """Request body for creating an agent."""

    model_config = ConfigDict(strict=False)

    name: str = Field(..., min_length=1, max_length=128)
    model: str = Field(..., min_length=1, max_length=128)
    capabilities: list[str] = Field(default_factory=list, max_length=64)
    tools: list[str] = Field(default_factory=list, max_length=64)
    memory_bindings: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> CreateAgentRequest:
        for cap in self.capabilities:
            if not cap or len(cap) > 128:
                msg = "capabilities entries must be 1..128 chars"
                raise ValueError(msg)
        for tool in self.tools:
            if not tool or len(tool) > 128:
                msg = "tools entries must be 1..128 chars"
                raise ValueError(msg)
        _validate_opaque_mapping(self.memory_bindings, field_name="memory_bindings")
        _validate_opaque_mapping(self.budget, field_name="budget")
        return self


class UpdateAgentRequest(BaseModel):
    """Request body for updating an agent. All fields optional — at least one required."""

    model_config = ConfigDict(strict=False)

    name: str | None = Field(None, min_length=1, max_length=128)
    model: str | None = Field(None, min_length=1, max_length=128)
    capabilities: list[str] | None = Field(None, max_length=64)
    tools: list[str] | None = Field(None, max_length=64)
    memory_bindings: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate(self) -> UpdateAgentRequest:
        provided = [
            self.name,
            self.model,
            self.capabilities,
            self.tools,
            self.memory_bindings,
            self.budget,
        ]
        if all(v is None for v in provided):
            msg = "at least one field must be provided"
            raise ValueError(msg)

        if self.capabilities is not None:
            for cap in self.capabilities:
                if not cap or len(cap) > 128:
                    msg = "capabilities entries must be 1..128 chars"
                    raise ValueError(msg)
        if self.tools is not None:
            for tool in self.tools:
                if not tool or len(tool) > 128:
                    msg = "tools entries must be 1..128 chars"
                    raise ValueError(msg)
        if self.memory_bindings is not None:
            _validate_opaque_mapping(self.memory_bindings, field_name="memory_bindings")
        if self.budget is not None:
            _validate_opaque_mapping(self.budget, field_name="budget")
        return self


class AgentResponse(BaseModel):
    """Response body for a single agent."""

    id: str
    workspace_id: str
    name: str
    status: AgentStatus
    model: str
    capabilities: list[str]
    tools: list[str]
    memory_bindings: dict[str, Any]
    budget: dict[str, Any]
    config_version: int
    current_config: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseModel):
    """Response body for listing agents."""

    agents: list[AgentResponse]
    count: int
    limit: int
    offset: int
    has_more: bool


class AgentConfigVersionResponse(BaseModel):
    """Response body for a single config version."""

    agent_id: str
    version: int
    config: dict[str, Any]
    changed_by: str
    changed_at: datetime


class AgentConfigVersionListResponse(BaseModel):
    """Response body for listing config versions."""

    versions: list[AgentConfigVersionResponse]
    count: int
    limit: int
    offset: int
    has_more: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_to_response(record: AgentRecord) -> AgentResponse:
    return AgentResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        name=record.name,
        status=record.status,
        model=record.model,
        capabilities=list(record.capabilities),
        tools=list(record.tools),
        memory_bindings=dict(record.memory_bindings),
        budget=dict(record.budget),
        config_version=record.config_version,
        current_config=dict(record.current_config),
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _version_to_response(version: AgentConfigVersion) -> AgentConfigVersionResponse:
    return AgentConfigVersionResponse(
        agent_id=version.agent_id,
        version=version.version,
        config=dict(version.config),
        changed_by=version.changed_by,
        changed_at=version.changed_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=AgentResponse,
    status_code=201,
)
async def create_agent(
    body: CreateAgentRequest,
    user: Annotated[User, Depends(require_editor)],
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Create a new agent. Status is forced to STOPPED; config_version=1."""
    try:
        record = await service.create_agent(
            name=body.name,
            model=body.model,
            capabilities=list(body.capabilities),
            tools=list(body.tools),
            memory_bindings=dict(body.memory_bindings),
            budget=dict(body.budget),
            created_by=user.id,
        )
    except AgentNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _agent_to_response(record)


@router.get("", response_model=AgentListResponse)
async def list_agents(
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    status: AgentStatus | None = None,
    name_prefix: str | None = Query(None, min_length=1, max_length=128),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> AgentListResponse:
    """List agents in the current workspace."""
    records = await service.list_agents(
        status=status,
        name_prefix=name_prefix,
        limit=limit + 1,
        offset=offset,
    )
    has_more = len(records) > limit
    trimmed = records[:limit]
    return AgentListResponse(
        agents=[_agent_to_response(r) for r in trimmed],
        count=len(trimmed),
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Fetch a single agent by id."""
    try:
        record = await service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return _agent_to_response(record)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    user: Annotated[User, Depends(require_editor)],
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Partial update — bumps ``config_version`` and records a version row."""
    try:
        record = await service.update_agent(
            agent_id,
            name=body.name,
            model=body.model,
            capabilities=body.capabilities,
            tools=body.tools,
            memory_bindings=body.memory_bindings,
            budget=body.budget,
            changed_by=user.id,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except AgentNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _agent_to_response(record)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> Response:
    """Soft-delete: flips status to ``ARCHIVED``. 404 if not found."""
    deleted = await service.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id!r}")
    return Response(status_code=204)


@router.post("/{agent_id}/start", response_model=AgentResponse)
async def start_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Set status to ACTIVE (no version bump)."""
    try:
        record = await service.start_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return _agent_to_response(record)


@router.post("/{agent_id}/stop", response_model=AgentResponse)
async def stop_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Set status to STOPPED (no version bump)."""
    try:
        record = await service.stop_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return _agent_to_response(record)


@router.post("/{agent_id}/pause", response_model=AgentResponse)
async def pause_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Set status to PAUSED (no version bump)."""
    try:
        record = await service.pause_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return _agent_to_response(record)


@router.get(
    "/{agent_id}/versions",
    response_model=AgentConfigVersionListResponse,
)
async def list_agent_versions(
    agent_id: str,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> AgentConfigVersionListResponse:
    """List historical config versions for an agent, newest first."""
    try:
        versions = await service.list_versions(
            agent_id,
            limit=limit + 1,
            offset=offset,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    has_more = len(versions) > limit
    trimmed = versions[:limit]
    return AgentConfigVersionListResponse(
        versions=[_version_to_response(v) for v in trimmed],
        count=len(trimmed),
        limit=limit,
        offset=offset,
        has_more=has_more,
    )
