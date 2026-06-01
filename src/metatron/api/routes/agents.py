"""Agent Registry REST API — /api/v1/agents.

Exposes CRUD, lifecycle transitions and config-version history for agents
in a workspace. Workspace is auth-derived by default; an optional
``?workspace_id`` query param overrides it when the caller's JWT grants access
("*" or membership), else 403 (``resolve_workspace_id``).

RBAC — aligns with the ``memory/`` module convention:

* ``viewer+`` — read-only endpoints: ``GET /``, ``GET /{id}``, ``GET /{id}/versions``
* ``editor+`` — write and lifecycle: ``POST /``, ``PUT /{id}``, ``DELETE /{id}``,
  ``POST /{id}/start|stop|pause``
"""

from __future__ import annotations

import json
from datetime import date, datetime  # noqa: TC003 — runtime for pydantic field validation
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from metatron.activity.service import (
    ActivityService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)
from metatron.agents.models import (
    AgentConfigVersion,  # noqa: TC001 — helper annotations need runtime resolution
    AgentRecord,  # noqa: TC001 — helper annotations need runtime resolution
    AgentStatus,  # noqa: TC001 — Pydantic field types need runtime resolution
)
from metatron.agents.service import (
    AgentInvalidStateTransitionError,
    AgentNameConflictError,
    AgentNotFoundError,
    AgentRegistryService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)
from metatron.api.dependencies import (
    get_agent_registry_service,
    get_memory_health_service,
    get_memory_service,
    get_memory_snapshot_service,
    resolve_workspace_id,
    workspace_scope,
)
from metatron.auth.dependencies import require_editor, require_viewer
from metatron.core.exceptions import (
    SnapshotCorruptError,
    SnapshotOverflowError,
    SnapshotStorageError,
)
from metatron.core.models import (
    MemorySnapshot,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
    User,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)
from metatron.memory.health import (
    AgentMemoryHealth,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
    MemoryHealthService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)
from metatron.memory.service import (
    MemoryService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)
from metatron.memory.snapshot import (
    MemorySnapshotService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
    SnapshotTrigger,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(workspace_scope)])


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
    "/",
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


@router.get("/", response_model=AgentListResponse)
async def list_agents(
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    status: AgentStatus | None = None,
    name_prefix: str | None = Query(None, min_length=1, max_length=128),
    include_archived: bool = Query(False),
    include_system: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> AgentListResponse:
    """List agents in the current workspace.

    By default, ARCHIVED (soft-deleted) agents are hidden.  Pass
    ``include_archived=true`` to surface them alongside live agents, OR pass
    ``status=archived`` to return only archived agents.

    The two flags are mutually exclusive — passing both ``status=...`` and
    ``include_archived=true`` is rejected with 400.  This keeps the contract
    unambiguous (per MTRNIX-324 R7).

    Workspace scoping (incl. the ``?workspace_id`` access check) is handled by
    the router-level ``workspace_scope`` dependency.
    """
    if status is not None and include_archived:
        raise HTTPException(
            status_code=400,
            detail="status and include_archived are mutually exclusive",
        )
    records = await service.list_agents(
        status=status,
        name_prefix=name_prefix,
        include_archived=include_archived,
        include_system=include_system,
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
    """Set status to ACTIVE (no version bump). 400 if source is ARCHIVED."""
    try:
        record = await service.start_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except AgentInvalidStateTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _agent_to_response(record)


@router.post("/{agent_id}/stop", response_model=AgentResponse)
async def stop_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Set status to STOPPED (no version bump). 400 if source is ARCHIVED."""
    try:
        record = await service.stop_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except AgentInvalidStateTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _agent_to_response(record)


@router.post("/{agent_id}/pause", response_model=AgentResponse)
async def pause_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Set status to PAUSED (no version bump). 400 if source is ARCHIVED."""
    try:
        record = await service.pause_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except AgentInvalidStateTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _agent_to_response(record)


@router.post("/{agent_id}/restore", response_model=AgentResponse)
async def restore_agent(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
) -> AgentResponse:
    """Restore a soft-deleted agent: ARCHIVED → STOPPED.

    The only path out of ARCHIVED. Lands in STOPPED — operators must
    explicitly ``/start`` afterwards. Returns 400 when the agent is not
    archived, 404 when missing, 409 if another non-archived agent has
    claimed the name in the meantime.
    """
    try:
        record = await service.restore_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except AgentInvalidStateTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except AgentNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _agent_to_response(record)


class ResetAgentMemoryResponse(BaseModel):
    """Response body for ``POST /agents/{id}/reset``."""

    snapshot_id: str
    deleted_count: int


@router.post(
    "/{agent_id}/reset",
    response_model=ResetAgentMemoryResponse,
    status_code=200,
)
async def reset_agent_memory(
    agent_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    reg_service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    mem_service: Annotated[MemoryService, Depends(get_memory_service)],
    snap_service: Annotated[MemorySnapshotService, Depends(get_memory_snapshot_service)],
) -> ResetAgentMemoryResponse:
    """Wipe an agent's memory after taking an automatic ``pre_reset`` snapshot.

    Pre-snapshot is created first — if it fails, the reset never happens, so
    operators always have an undo point.

    If the wipe itself fails *after* the snapshot was committed, the response
    is a 500 whose ``detail`` includes the snapshot id so the operator can
    recover via ``POST /api/v1/snapshots/{snapshot_id}/restore`` rather than
    being left with an orphaned snapshot row.
    """
    try:
        await reg_service.get_agent(agent_id)  # 404 if unknown
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    try:
        snapshot = await snap_service.create(
            agent_id,
            label="auto pre-reset snapshot",
            trigger=SnapshotTrigger.PRE_RESET,
        )
    except SnapshotOverflowError as exc:
        # >10k-records guard or on-disk size cap. 413 — request can't be
        # fulfilled until pagination / size-aware export ships.
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except SnapshotCorruptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SnapshotStorageError as exc:
        # Snapshot directory unwritable (e.g. permissions on mounted volume).
        raise HTTPException(status_code=503, detail=str(exc)) from None

    try:
        deleted = await mem_service.reset(reg_service.workspace_id, agent_id=agent_id)
    except Exception as exc:
        # The pre_reset snapshot succeeded but the wipe failed — the system
        # is in a partially-consistent state. Surface the snapshot id so the
        # operator can either retry the reset or restore from the snapshot.
        raise HTTPException(
            status_code=500,
            detail={
                "message": (
                    "reset failed after pre_reset snapshot was taken; "
                    "use the snapshot id to restore or retry"
                ),
                "snapshot_id": snapshot.id,
                "error": str(exc),
            },
        ) from exc

    return ResetAgentMemoryResponse(
        snapshot_id=snapshot.id,
        deleted_count=deleted,
    )


class CreateSnapshotRequest(BaseModel):
    """Request body for creating a manual memory snapshot."""

    model_config = ConfigDict(strict=False)

    label: str = Field("", max_length=256)


class MemorySnapshotResponse(BaseModel):
    """Response shape for a single :class:`MemorySnapshot`."""

    id: str
    workspace_id: str
    agent_id: str
    label: str
    trigger: str
    record_count: int
    content_hash: str
    size_bytes: int
    storage_path: str
    created_at: datetime


class MemorySnapshotListResponse(BaseModel):
    """Response shape for listing snapshots for an agent."""

    snapshots: list[MemorySnapshotResponse]
    count: int


def _snapshot_to_response(snapshot: MemorySnapshot) -> MemorySnapshotResponse:
    return MemorySnapshotResponse(
        id=snapshot.id,
        workspace_id=snapshot.workspace_id,
        agent_id=snapshot.agent_id,
        label=snapshot.label,
        trigger=snapshot.trigger,
        record_count=snapshot.record_count,
        content_hash=snapshot.content_hash,
        size_bytes=snapshot.size_bytes,
        storage_path=snapshot.storage_path,
        created_at=snapshot.created_at,
    )


@router.post(
    "/{agent_id}/snapshots",
    response_model=MemorySnapshotResponse,
    status_code=201,
)
async def create_agent_snapshot(
    agent_id: str,
    body: CreateSnapshotRequest,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    reg_service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    snap_service: Annotated[MemorySnapshotService, Depends(get_memory_snapshot_service)],
) -> MemorySnapshotResponse:
    """Take a manual snapshot of the agent's current memory."""
    try:
        await reg_service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    try:
        snapshot = await snap_service.create(
            agent_id,
            label=body.label,
            trigger=SnapshotTrigger.MANUAL,
        )
    except SnapshotOverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except SnapshotCorruptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SnapshotStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return _snapshot_to_response(snapshot)


@router.get(
    "/{agent_id}/snapshots",
    response_model=MemorySnapshotListResponse,
)
async def list_agent_snapshots(
    agent_id: str,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    reg_service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    snap_service: Annotated[MemorySnapshotService, Depends(get_memory_snapshot_service)],
) -> MemorySnapshotListResponse:
    """List snapshots for an agent, newest first."""
    try:
        await reg_service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    snapshots = await snap_service.list_snapshots(agent_id)
    return MemorySnapshotListResponse(
        snapshots=[_snapshot_to_response(s) for s in snapshots],
        count=len(snapshots),
    )


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


# ---------------------------------------------------------------------------
# Memory health (MTRNIX-277)
# ---------------------------------------------------------------------------


class GrowthBucketResponse(BaseModel):
    """One day in the 30-day memory growth timeseries."""

    day: date
    created_count: int


class MemoryHealthResponse(BaseModel):
    """Read-only health snapshot for an agent's memory."""

    agent_id: str
    total_records: int
    total_archived: int
    growth_rate_per_day: float
    growth_timeseries: list[GrowthBucketResponse]
    unused_records: int
    unused_threshold_days: int
    duplicate_ratio: float
    duplicate_clusters_count: int
    duplicate_hamming_threshold: int
    source_distribution: dict[str, int]
    computed_at: datetime
    # When the ACTIVE-record count exceeds the hard cap, dup detection is
    # skipped to keep the endpoint cheap. The dashboard renders the badge
    # as "Skipped — over Nk records" instead of misleading 0% duplicates.
    duplicate_detection_skipped: bool = False
    duplicate_active_population: int = 0


def _health_to_response(h: AgentMemoryHealth) -> MemoryHealthResponse:
    return MemoryHealthResponse(
        agent_id=h.agent_id,
        total_records=h.total_records,
        total_archived=h.total_archived,
        growth_rate_per_day=h.growth_rate_per_day,
        growth_timeseries=[
            GrowthBucketResponse(day=b.day, created_count=b.created_count)
            for b in h.growth_timeseries
        ],
        unused_records=h.unused_records,
        unused_threshold_days=h.unused_threshold_days,
        duplicate_ratio=h.duplicate_ratio,
        duplicate_clusters_count=h.duplicate_clusters_count,
        duplicate_hamming_threshold=h.duplicate_hamming_threshold,
        source_distribution=dict(h.source_distribution),
        computed_at=h.computed_at,
        duplicate_detection_skipped=h.duplicate_detection_skipped,
        duplicate_active_population=h.duplicate_active_population,
    )


@router.get(
    "/{agent_id}/memory/health",
    response_model=MemoryHealthResponse,
)
async def get_agent_memory_health(
    agent_id: str,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    reg_service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    health_service: Annotated[MemoryHealthService, Depends(get_memory_health_service)],
) -> MemoryHealthResponse:
    """Read-only memory health snapshot for an agent."""
    try:
        agent = await reg_service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    if agent.workspace_id != reg_service.workspace_id:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id!r}")

    health = await health_service.compute(agent_id)
    return _health_to_response(health)


# ---------------------------------------------------------------------------
# Activity (WS4 S6)
# ---------------------------------------------------------------------------


class ActivityEventResponse(BaseModel):
    id: int
    workspace_id: str
    agent_id: str
    session_id: str | None
    event_type: str
    event_data: dict[str, Any]
    created_at: datetime


class ActivityListResponse(BaseModel):
    events: list[ActivityEventResponse]
    count: int
    limit: int
    offset: int
    has_more: bool


class ActivitySummaryResponse(BaseModel):
    period: str
    since: str
    until: str
    total_events: int
    counts_by_event_type: dict[str, int]
    counts_by_day: list[dict[str, Any]]


def get_activity_service(request: Request) -> ActivityService:
    """Per-workspace ActivityService, reusing the store wired in create_app()."""
    store = getattr(request.app.state, "activity_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="activity log disabled")
    workspace_id = resolve_workspace_id(request)
    return ActivityService(store=store, workspace_id=workspace_id)


@router.get(
    "/{agent_id}/activity",
    response_model=ActivityListResponse,
)
async def get_agent_activity(
    agent_id: str,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    reg_service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    act_service: Annotated[ActivityService, Depends(get_activity_service)],
    since: datetime | None = None,
    until: datetime | None = None,
    event_type: list[str] | None = Query(None),  # noqa: B008
    session_id: str | None = Query(None, min_length=1, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> ActivityListResponse:
    """Paginated activity timeline for a single agent."""
    try:
        agent = await reg_service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    # Defence-in-depth: registry already filters by workspace, but explicit
    # cross-check guarantees we never leak activity from a foreign workspace
    # if the registry layer ever regresses.
    if agent.workspace_id != reg_service.workspace_id:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id!r}")

    events, has_more = await act_service.list_for_agent(
        agent_id=agent_id,
        since=since,
        until=until,
        event_types=event_type,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return ActivityListResponse(
        events=[
            ActivityEventResponse(
                id=int(r["id"]),
                workspace_id=r["workspace_id"],
                agent_id=r["agent_id"],
                session_id=r["session_id"],
                event_type=r["event_type"],
                event_data=dict(r["event_data"] or {}),
                created_at=r["created_at"],
            )
            for r in events
        ],
        count=len(events),
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get(
    "/{agent_id}/activity/summary",
    response_model=ActivitySummaryResponse,
)
async def get_agent_activity_summary(
    agent_id: str,
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    reg_service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
    act_service: Annotated[ActivityService, Depends(get_activity_service)],
    period: str = Query("7d"),
) -> ActivitySummaryResponse:
    """Aggregated stats over `period` (1d | 7d | 30d | 90d)."""
    try:
        agent = await reg_service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    if agent.workspace_id != reg_service.workspace_id:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id!r}")

    try:
        payload = await act_service.summary_for_agent(agent_id=agent_id, period=period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return ActivitySummaryResponse(**payload)
