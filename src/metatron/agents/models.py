"""Dataclass shapes for the Agent Registry (WS4).

Pure transport dataclasses — no ORM, no Pydantic, no business logic.
Mirror the memory module pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class AgentStatus(StrEnum):
    """Lifecycle status of an agent entry.

    ACTIVE   — agent is running and may accept work.
    PAUSED   — agent is temporarily suspended.
    STOPPED  — agent is idle (default for newly created agents).
    ARCHIVED — soft-deleted; excluded from list by default.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ARCHIVED = "archived"


@dataclass
class AgentRecord:
    """Single agent registry entry.

    ``current_config`` is an opaque snapshot of the configuration fields
    (name, model, capabilities, tools, memory_bindings, budget) that can
    be versioned and rolled back via ``agent_config_versions``.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    workspace_id: str = ""
    name: str = ""
    status: AgentStatus = AgentStatus.STOPPED
    model: str = ""
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    memory_bindings: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    config_version: int = 1
    current_config: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AgentConfigVersion:
    """Historical snapshot of an agent's configuration at a given version."""

    agent_id: str = ""
    version: int = 0
    config: dict[str, Any] = field(default_factory=dict)
    changed_by: str = ""
    changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
