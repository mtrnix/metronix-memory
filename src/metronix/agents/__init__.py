"""Agent Registry (WS4).

L3 service module. Provides CRUD, lifecycle flagging, and config-version
history for agents registered in a workspace. This is the backend piece of
the Control Center — a public REST surface under ``/api/v1/agents``.

The module deliberately mirrors the layout of ``metronix.memory``:

* ``models`` — pure dataclasses (``AgentRecord``, ``AgentConfigVersion``)
* ``persistence`` — async PostgreSQL store (``AgentPersistence``)
* ``service`` — orchestration + typed errors (``AgentRegistryService``)
"""

from metronix.agents.models import AgentConfigVersion, AgentRecord, AgentStatus
from metronix.agents.persistence import AgentPersistence
from metronix.agents.service import (
    AgentInvalidStateTransitionError,
    AgentNameConflictError,
    AgentNotFoundError,
    AgentRegistryService,
)

__all__ = [
    "AgentConfigVersion",
    "AgentInvalidStateTransitionError",
    "AgentNameConflictError",
    "AgentNotFoundError",
    "AgentPersistence",
    "AgentRecord",
    "AgentRegistryService",
    "AgentStatus",
]
