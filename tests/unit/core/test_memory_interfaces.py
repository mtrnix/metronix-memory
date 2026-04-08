"""Tests for agent memory interfaces (WS1)."""

from __future__ import annotations

import pytest

from metatron.core.interfaces import MemoryStoreInterface, SessionMemoryInterface
from metatron.core.models import (
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    MemorySnapshot,
)


def test_memory_store_interface_is_abstract() -> None:
    with pytest.raises(TypeError):
        MemoryStoreInterface()  # type: ignore[abstract]


def test_session_memory_interface_is_abstract() -> None:
    with pytest.raises(TypeError):
        SessionMemoryInterface()  # type: ignore[abstract]


def test_memory_store_abstract_methods() -> None:
    expected = {
        "save",
        "get",
        "search",
        "delete",
        "list",
        "reset",
        "create_snapshot",
        "restore_snapshot",
    }
    assert expected <= MemoryStoreInterface.__abstractmethods__


def test_session_memory_abstract_methods() -> None:
    expected = {"cache", "get", "list", "invalidate", "extend_ttl", "promote"}
    assert expected <= SessionMemoryInterface.__abstractmethods__


class _DummyStore(MemoryStoreInterface):
    async def save(self, workspace_id: str, record: MemoryRecord) -> MemoryRecord:
        return record

    async def get(self, workspace_id: str, record_id: str) -> MemoryRecord | None:
        return None

    async def search(
        self,
        workspace_id: str,
        query: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        tags: list[str] | None = None,
        top_k: int = 5,
    ) -> list[MemorySearchResult]:
        return []

    async def delete(self, workspace_id: str, record_id: str) -> bool:
        return False

    async def list(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        return []

    async def reset(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
    ) -> int:
        return 0

    async def create_snapshot(
        self,
        workspace_id: str,
        agent_id: str,
        *,
        label: str = "",
        trigger: str = "manual",
    ) -> MemorySnapshot:
        return MemorySnapshot(workspace_id=workspace_id, agent_id=agent_id)

    async def restore_snapshot(self, workspace_id: str, snapshot_id: str) -> int:
        return 0


class _DummySession(SessionMemoryInterface):
    async def cache(
        self,
        workspace_id: str,
        session_id: str,
        record: MemoryRecord,
        *,
        ttl_seconds: int | None = None,
    ) -> MemoryRecord:
        return record

    async def get(self, workspace_id: str, session_id: str, record_id: str) -> MemoryRecord | None:
        return None

    async def list(self, workspace_id: str, session_id: str) -> list[MemoryRecord]:
        return []

    async def invalidate(self, workspace_id: str, session_id: str) -> int:
        return 0

    async def extend_ttl(self, workspace_id: str, session_id: str, ttl_seconds: int) -> bool:
        return True

    async def promote(
        self,
        workspace_id: str,
        session_id: str,
        record_id: str,
        *,
        target_scope: MemoryScope = MemoryScope.PER_AGENT,
    ) -> MemoryRecord:
        return MemoryRecord(id=record_id, workspace_id=workspace_id, scope=target_scope)


def test_concrete_memory_store_implementable() -> None:
    store = _DummyStore()
    assert isinstance(store, MemoryStoreInterface)


def test_concrete_session_memory_implementable() -> None:
    session = _DummySession()
    assert isinstance(session, SessionMemoryInterface)
