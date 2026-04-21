"""AgentRegistryService — CRUD + lifecycle orchestration for WS4.

L3 service layer. Wraps :class:`AgentPersistence` with workspace-binding,
partial-merge semantics, and lifecycle transitions. Mirrors the MemoryService
pattern: one service instance per workspace, business errors raised as typed
subclasses of :class:`MetatronError`.

Design decisions:

* ``memory_bindings`` and ``budget`` are opaque JSONB blobs. The registry
  stores them but does not interpret or validate the shape beyond basic
  dict/list typing.
* Status transitions (start / stop / pause / archive) do NOT bump the config
  version. Versioning tracks *configuration* changes only.
* ``delete_agent`` is a soft-delete that flips status to ARCHIVED; no rows
  are removed. This is intentional so audit trails stay intact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from metatron.agents.models import AgentConfigVersion, AgentRecord, AgentStatus
from metatron.agents.persistence import _AgentNameConflictError
from metatron.core.exceptions import MetatronError

if TYPE_CHECKING:
    from metatron.agents.persistence import AgentPersistence

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AgentNotFoundError(MetatronError):
    """Requested agent does not exist in this workspace."""


class AgentNameConflictError(MetatronError):
    """An agent with the same ``name`` already exists in this workspace."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AgentRegistryService:
    """Per-workspace orchestration over :class:`AgentPersistence`.

    The workspace is bound at construction — route handlers look up the
    service on ``app.state.agent_registry_services`` keyed by workspace.
    """

    def __init__(self, repo: AgentPersistence, *, workspace_id: str) -> None:
        self._repo = repo
        self._workspace_id = workspace_id

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_snapshot(record: AgentRecord) -> dict[str, Any]:
        """Return the versioned slice of an agent record.

        Excludes id, workspace_id, status, config_version, timestamps,
        created_by — these are not part of the rolling config snapshot.
        """
        return {
            "name": record.name,
            "model": record.model,
            "capabilities": list(record.capabilities),
            "tools": list(record.tools),
            "memory_bindings": dict(record.memory_bindings),
            "budget": dict(record.budget),
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_agent(
        self,
        *,
        name: str,
        model: str,
        capabilities: list[str] | None = None,
        tools: list[str] | None = None,
        memory_bindings: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        created_by: str,
    ) -> AgentRecord:
        """Create a new agent. Status is forced to STOPPED, version=1."""
        record = AgentRecord(
            workspace_id=self._workspace_id,
            name=name,
            status=AgentStatus.STOPPED,
            model=model,
            capabilities=list(capabilities or []),
            tools=list(tools or []),
            memory_bindings=dict(memory_bindings or {}),
            budget=dict(budget or {}),
            config_version=1,
            created_by=created_by,
        )
        record.current_config = self._build_snapshot(record)
        try:
            return await self._repo.save_new(record)
        except _AgentNameConflictError as exc:
            raise AgentNameConflictError(str(exc)) from exc

    async def get_agent(self, agent_id: str) -> AgentRecord:
        """Fetch an agent by id. Raises :class:`AgentNotFoundError`."""
        record = await self._repo.get(self._workspace_id, agent_id)
        if record is None:
            raise AgentNotFoundError(f"agent not found: {agent_id!r}")
        return record

    async def list_agents(
        self,
        *,
        status: AgentStatus | None = None,
        name_prefix: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentRecord]:
        """List agents with optional filters and pagination."""
        return await self._repo.list_records(
            self._workspace_id,
            status=status,
            name_prefix=name_prefix,
            limit=limit,
            offset=offset,
        )

    async def update_agent(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        model: str | None = None,
        capabilities: list[str] | None = None,
        tools: list[str] | None = None,
        memory_bindings: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        changed_by: str,
    ) -> AgentRecord:
        """Partial update — unset fields keep their current value.

        The full post-update snapshot is stored in both ``current_config``
        and the new ``agent_config_versions`` row, so each version row is
        self-contained (rollback does not require replaying the chain).
        """
        existing = await self.get_agent(agent_id)

        merged: dict[str, Any] = self._build_snapshot(existing)
        if name is not None:
            merged["name"] = name
        if model is not None:
            merged["model"] = model
        if capabilities is not None:
            merged["capabilities"] = list(capabilities)
        if tools is not None:
            merged["tools"] = list(tools)
        if memory_bindings is not None:
            merged["memory_bindings"] = dict(memory_bindings)
        if budget is not None:
            merged["budget"] = dict(budget)

        new_fields: dict[str, Any] = dict(merged)
        new_fields["current_config"] = dict(merged)

        try:
            updated = await self._repo.update_with_version_bump(
                self._workspace_id,
                agent_id,
                new_fields=new_fields,
                changed_by=changed_by,
            )
        except _AgentNameConflictError as exc:
            raise AgentNameConflictError(str(exc)) from exc

        if updated is None:
            # Existed on pre-check, vanished under FOR UPDATE — treat as 404.
            raise AgentNotFoundError(f"agent not found: {agent_id!r}")
        return updated

    async def delete_agent(self, agent_id: str) -> bool:
        """Soft-delete by flipping status to ARCHIVED.

        Returns True if the agent was found and archived; False if it did
        not exist.
        """
        record = await self._repo.update_status(
            self._workspace_id,
            agent_id,
            AgentStatus.ARCHIVED,
        )
        return record is not None

    # ------------------------------------------------------------------
    # Lifecycle (no version bump)
    # ------------------------------------------------------------------

    async def start_agent(self, agent_id: str) -> AgentRecord:
        return await self._transition_status(agent_id, AgentStatus.ACTIVE)

    async def stop_agent(self, agent_id: str) -> AgentRecord:
        return await self._transition_status(agent_id, AgentStatus.STOPPED)

    async def pause_agent(self, agent_id: str) -> AgentRecord:
        return await self._transition_status(agent_id, AgentStatus.PAUSED)

    async def _transition_status(self, agent_id: str, status: AgentStatus) -> AgentRecord:
        record = await self._repo.update_status(self._workspace_id, agent_id, status)
        if record is None:
            raise AgentNotFoundError(f"agent not found: {agent_id!r}")
        return record

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    async def list_versions(
        self,
        agent_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentConfigVersion]:
        """List historical config versions for an agent, newest first.

        Pre-checks the agent exists so callers get a clean 404 rather than
        an empty list for typos.
        """
        await self.get_agent(agent_id)
        return await self._repo.list_versions(
            self._workspace_id,
            agent_id,
            limit=limit,
            offset=offset,
        )
