"""PostgreSQL persistence for the Agent Registry (WS4).

Source of truth for agent entries and config version history.
Uses raw SQL via SQLAlchemy async engine — same pattern as
``storage/memory_postgres.py``.

This is an L3 module (co-located with the registry service) because the
registry is a thin orchestration layer around a single store. It deliberately
does NOT live under ``storage/`` to match the domain-first layout used by
``memory/`` sibling modules.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from metronix.agents.models import AgentConfigVersion, AgentRecord, AgentStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Column groups
# ---------------------------------------------------------------------------

_AGENT_COLUMNS = (
    "id, workspace_id, name, status, model, capabilities, tools, "
    "memory_bindings, budget, config_version, current_config, is_system, "
    "created_by, created_at, updated_at"
)

_VERSION_COLUMNS = "agent_id, version, config, changed_by, changed_at"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class _AgentNameConflictError(Exception):
    """Raised when an agent with the same ``(workspace_id, name)`` already exists.

    Module-private. The service layer catches this and re-raises a
    :class:`metronix.agents.service.AgentNameConflictError` (a
    :class:`MetronixError` subclass) that routes map to HTTP 409.
    """


class _AgentIdConflictError(Exception):
    """Raised when an agent with the same ``id`` (primary key) already exists.

    Only reachable when the caller supplies a pre-generated id — generated
    ``uuid4`` ids never collide in practice. Module-private; the service layer
    re-raises it as the public :class:`metronix.agents.service.AgentIdConflictError`
    (HTTP 409). Distinguished from :class:`_AgentNameConflictError` by inspecting
    which constraint the INSERT violated.
    """


def _classify_insert_conflict(exc: IntegrityError) -> str:
    """Classify an ``agents`` INSERT IntegrityError as ``"id"`` or ``"name"``.

    The two constraints an insert can violate are the primary key
    (``agents_pkey`` — duplicate id) and the partial unique index
    (``uq_agents_workspace_name`` — duplicate name in the workspace).
    asyncpg exposes the violated constraint both as ``orig.constraint_name``
    and in the error text; we check both for robustness.

    Defaults to ``"name"`` when the constraint cannot be identified so the
    historical "409 on duplicate name" contract never regresses.
    """
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", "") or ""
    haystack = f"{constraint} {exc}".lower()
    if "uq_agents_workspace_name" in haystack:
        return "name"
    if "agents_pkey" in haystack:
        return "id"
    return "name"


# ---------------------------------------------------------------------------
# Row → dataclass helpers
# ---------------------------------------------------------------------------


def _ensure_tz(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _json_field(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    return json.loads(value)


def _row_to_record(m: Any) -> AgentRecord:
    """Convert a DB row mapping to AgentRecord."""
    created = _ensure_tz(m["created_at"]) or datetime.now(UTC)
    updated = _ensure_tz(m["updated_at"]) or created
    return AgentRecord(
        id=m["id"],
        workspace_id=m["workspace_id"],
        name=m["name"],
        status=AgentStatus(m["status"]),
        model=m["model"],
        capabilities=list(_json_field(m["capabilities"], [])),
        tools=list(_json_field(m["tools"], [])),
        memory_bindings=dict(_json_field(m["memory_bindings"], {})),
        budget=dict(_json_field(m["budget"], {})),
        config_version=int(m["config_version"]),
        current_config=dict(_json_field(m["current_config"], {})),
        is_system=bool(m.get("is_system", False)),
        created_by=m["created_by"] or "",
        created_at=created,
        updated_at=updated,
    )


def _row_to_version(m: Any) -> AgentConfigVersion:
    """Convert a DB row mapping to AgentConfigVersion."""
    changed = _ensure_tz(m["changed_at"]) or datetime.now(UTC)
    return AgentConfigVersion(
        agent_id=m["agent_id"],
        version=int(m["version"]),
        config=dict(_json_field(m["config"], {})),
        changed_by=m["changed_by"] or "",
        changed_at=changed,
    )


def _escape_like_prefix(prefix: str) -> str:
    """Escape ``%`` and ``_`` so they are matched literally in a LIKE prefix."""
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class AgentPersistence:
    """Async PostgreSQL store for agent registry rows and config versions."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Agents — CRUD
    # ------------------------------------------------------------------

    async def save_new(self, record: AgentRecord) -> AgentRecord:
        """Insert a new agent and seed its first config version.

        Runs in a single transaction. Raises :class:`_AgentNameConflictError`
        when ``(workspace_id, name)`` is already taken.
        """
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    text(f"""
                        INSERT INTO agents ({_AGENT_COLUMNS})
                        VALUES (:id, :workspace_id, :name, :status, :model,
                                CAST(:capabilities AS jsonb),
                                CAST(:tools AS jsonb),
                                CAST(:memory_bindings AS jsonb),
                                CAST(:budget AS jsonb),
                                :config_version,
                                CAST(:current_config AS jsonb),
                                :is_system,
                                :created_by, :created_at, :updated_at)
                    """),
                    {
                        "id": record.id,
                        "workspace_id": record.workspace_id,
                        "name": record.name,
                        "status": record.status.value,
                        "model": record.model,
                        "capabilities": json.dumps(list(record.capabilities)),
                        "tools": json.dumps(list(record.tools)),
                        "memory_bindings": json.dumps(dict(record.memory_bindings)),
                        "budget": json.dumps(dict(record.budget)),
                        "config_version": record.config_version,
                        "current_config": json.dumps(dict(record.current_config)),
                        "is_system": record.is_system,
                        "created_by": record.created_by,
                        "created_at": record.created_at,
                        "updated_at": record.updated_at,
                    },
                )
                await conn.execute(
                    text(f"""
                        INSERT INTO agent_config_versions ({_VERSION_COLUMNS})
                        VALUES (:agent_id, :version, CAST(:config AS jsonb),
                                :changed_by, :changed_at)
                    """),
                    {
                        "agent_id": record.id,
                        "version": record.config_version,
                        "config": json.dumps(dict(record.current_config)),
                        "changed_by": record.created_by,
                        "changed_at": record.created_at,
                    },
                )
        except IntegrityError as exc:
            if _classify_insert_conflict(exc) == "id":
                logger.debug("agents_pg.save_new_id_conflict", agent_id=record.id, error=str(exc))
                raise _AgentIdConflictError(f"agent id already exists: {record.id!r}") from exc
            logger.debug("agents_pg.save_new_conflict", agent_id=record.id, error=str(exc))
            raise _AgentNameConflictError(
                f"agent name already exists in workspace: {record.name!r}"
            ) from exc

        logger.debug("agents_pg.saved", agent_id=record.id)
        return record

    async def get(self, workspace_id: str, agent_id: str) -> AgentRecord | None:
        """Fetch an agent by id within the workspace."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_AGENT_COLUMNS}
                    FROM agents
                    WHERE id = :id AND workspace_id = :ws
                """),
                {"id": agent_id, "ws": workspace_id},
            )
            row = result.first()
        if row is None:
            return None
        return _row_to_record(row._mapping)

    async def list_records(
        self,
        workspace_id: str,
        *,
        status: AgentStatus | None = None,
        name_prefix: str | None = None,
        include_archived: bool = False,
        include_system: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentRecord]:
        """List agents with optional filters and pagination.

        Filter precedence (highest to lowest):

        1. If ``status`` is not None — return only agents with that exact status.
           ``include_archived`` is ignored in this branch (callers that need fine-grained
           control already pass an explicit status).
        2. Elif ``include_archived=True`` — return all agents regardless of status
           (no WHERE clause added for status).
        3. Else (default) — exclude ARCHIVED agents.  This is the "show everything
           except soft-deleted" view used by the default list endpoint.
        """
        where_parts = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": workspace_id, "limit": limit, "offset": offset}

        if status is not None:
            where_parts.append("status = :status")
            params["status"] = status.value
        elif not include_archived:
            # Soft-deleted (archived) agents are hidden by default.
            # Clients can opt in explicitly via ``?status=archived`` or
            # ``?include_archived=true``.
            where_parts.append("status <> :archived_status")
            params["archived_status"] = AgentStatus.ARCHIVED.value
        # else: include_archived=True — no status WHERE clause; all rows returned.
        if not include_system:
            where_parts.append("is_system = false")
        if name_prefix is not None and name_prefix != "":
            where_parts.append("name LIKE :name_prefix ESCAPE '\\'")
            params["name_prefix"] = _escape_like_prefix(name_prefix) + "%"

        where_clause = " AND ".join(where_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_AGENT_COLUMNS}
                    FROM agents
                    WHERE {where_clause}
                    ORDER BY created_at DESC, id ASC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()
        return [_row_to_record(r._mapping) for r in rows]

    async def update_with_version_bump(
        self,
        workspace_id: str,
        agent_id: str,
        *,
        new_fields: dict[str, Any],
        changed_by: str,
    ) -> AgentRecord | None:
        """Apply a partial update and bump the config version.

        Runs in a single transaction with SELECT ... FOR UPDATE to avoid
        concurrent version races. Returns the updated record or ``None`` if
        the agent does not exist.

        Raises :class:`_AgentNameConflictError` if the resulting name collides
        with another agent in the same workspace.
        """
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text(f"""
                        SELECT {_AGENT_COLUMNS}
                        FROM agents
                        WHERE id = :id AND workspace_id = :ws
                        FOR UPDATE
                    """),
                    {"id": agent_id, "ws": workspace_id},
                )
                row = result.first()
                if row is None:
                    return None

                existing = _row_to_record(row._mapping)
                merged = AgentRecord(
                    id=existing.id,
                    workspace_id=existing.workspace_id,
                    name=new_fields.get("name", existing.name),
                    status=existing.status,
                    model=new_fields.get("model", existing.model),
                    capabilities=list(new_fields.get("capabilities", existing.capabilities)),
                    tools=list(new_fields.get("tools", existing.tools)),
                    memory_bindings=dict(
                        new_fields.get("memory_bindings", existing.memory_bindings)
                    ),
                    budget=dict(new_fields.get("budget", existing.budget)),
                    config_version=existing.config_version + 1,
                    current_config=dict(new_fields.get("current_config", existing.current_config)),
                    created_by=existing.created_by,
                    created_at=existing.created_at,
                    updated_at=datetime.now(UTC),
                )

                await conn.execute(
                    text("""
                        UPDATE agents
                        SET name = :name,
                            model = :model,
                            capabilities = CAST(:capabilities AS jsonb),
                            tools = CAST(:tools AS jsonb),
                            memory_bindings = CAST(:memory_bindings AS jsonb),
                            budget = CAST(:budget AS jsonb),
                            config_version = :config_version,
                            current_config = CAST(:current_config AS jsonb),
                            updated_at = :updated_at
                        WHERE id = :id AND workspace_id = :ws
                    """),
                    {
                        "id": merged.id,
                        "ws": merged.workspace_id,
                        "name": merged.name,
                        "model": merged.model,
                        "capabilities": json.dumps(list(merged.capabilities)),
                        "tools": json.dumps(list(merged.tools)),
                        "memory_bindings": json.dumps(dict(merged.memory_bindings)),
                        "budget": json.dumps(dict(merged.budget)),
                        "config_version": merged.config_version,
                        "current_config": json.dumps(dict(merged.current_config)),
                        "updated_at": merged.updated_at,
                    },
                )

                await conn.execute(
                    text(f"""
                        INSERT INTO agent_config_versions ({_VERSION_COLUMNS})
                        VALUES (:agent_id, :version, CAST(:config AS jsonb),
                                :changed_by, :changed_at)
                    """),
                    {
                        "agent_id": merged.id,
                        "version": merged.config_version,
                        "config": json.dumps(dict(merged.current_config)),
                        "changed_by": changed_by,
                        "changed_at": merged.updated_at,
                    },
                )
        except IntegrityError as exc:
            logger.debug(
                "agents_pg.update_conflict",
                agent_id=agent_id,
                error=str(exc),
            )
            raise _AgentNameConflictError("agent name already exists in workspace") from exc

        logger.debug(
            "agents_pg.updated",
            agent_id=agent_id,
            version=merged.config_version,
        )
        return merged

    async def update_status(
        self,
        workspace_id: str,
        agent_id: str,
        status: AgentStatus,
    ) -> AgentRecord | None:
        """Update the lifecycle status flag (no version bump).

        Raises :class:`_AgentNameConflictError` if the new status would put
        the row back into the ``(workspace_id, name) WHERE status <> 'archived'``
        partial-unique index window and another agent has claimed the name in
        the meantime — relevant for the ARCHIVED → STOPPED restore path.
        """
        now = datetime.now(UTC)
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text(f"""
                        UPDATE agents
                        SET status = :status, updated_at = :updated_at
                        WHERE id = :id AND workspace_id = :ws
                        RETURNING {_AGENT_COLUMNS}
                    """),
                    {
                        "id": agent_id,
                        "ws": workspace_id,
                        "status": status.value,
                        "updated_at": now,
                    },
                )
                row = result.first()
        except IntegrityError as exc:
            logger.debug(
                "agents_pg.update_status_conflict",
                agent_id=agent_id,
                error=str(exc),
            )
            raise _AgentNameConflictError("agent name already exists in workspace") from exc
        if row is None:
            return None
        return _row_to_record(row._mapping)

    async def list_versions(
        self,
        workspace_id: str,
        agent_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentConfigVersion]:
        """List historical config versions for an agent, newest first.

        Joins ``agents`` to enforce workspace isolation — callers cannot read
        the version history of agents in other workspaces even by guessing id.
        """
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_VERSION_COLUMNS}
                    FROM agent_config_versions v
                    JOIN agents a ON a.id = v.agent_id
                    WHERE v.agent_id = :id AND a.workspace_id = :ws
                    ORDER BY v.version DESC
                    LIMIT :limit OFFSET :offset
                """),
                {
                    "id": agent_id,
                    "ws": workspace_id,
                    "limit": limit,
                    "offset": offset,
                },
            )
            rows = result.fetchall()
        return [_row_to_version(r._mapping) for r in rows]
