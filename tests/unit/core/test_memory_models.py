"""Tests for agent memory dataclasses (WS1)."""

from __future__ import annotations

from datetime import UTC, datetime

from metronix.core.models import (
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    MemorySnapshot,
)


def test_memory_scope_values() -> None:
    assert MemoryScope.GLOBAL == "global"
    assert MemoryScope.PER_AGENT == "per_agent"
    assert MemoryScope.SESSION == "session"
    assert len(list(MemoryScope)) == 3


def test_memory_record_defaults() -> None:
    record = MemoryRecord()
    assert len(record.id) == 32
    assert record.scope == MemoryScope.PER_AGENT
    assert record.tags == []
    assert record.metadata == {}
    assert record.importance_score == 0.5
    assert record.ttl_expires_at is None
    assert record.session_id is None
    assert record.created_at.tzinfo == UTC


def test_memory_record_full_construction() -> None:
    now = datetime.now(UTC)
    record = MemoryRecord(
        id="abc123",
        workspace_id="ws1",
        agent_id="agent-a",
        scope=MemoryScope.GLOBAL,
        source_type="user_statement",
        content="hello",
        tags=["graph:entity", "topic"],
        importance_score=0.9,
        ttl_expires_at=now,
        content_hash="deadbeef",
        created_at=now,
        session_id="sess-1",
        metadata={"k": "v"},
    )
    assert record.id == "abc123"
    assert record.workspace_id == "ws1"
    assert record.agent_id == "agent-a"
    assert record.scope == MemoryScope.GLOBAL
    assert record.source_type == "user_statement"
    assert record.content == "hello"
    assert record.tags == ["graph:entity", "topic"]
    assert record.importance_score == 0.9
    assert record.ttl_expires_at == now
    assert record.content_hash == "deadbeef"
    assert record.created_at == now
    assert record.session_id == "sess-1"
    assert record.metadata == {"k": "v"}


def test_memory_record_unique_ids() -> None:
    assert MemoryRecord().id != MemoryRecord().id


def test_memory_snapshot_defaults() -> None:
    snap = MemorySnapshot()
    assert len(snap.id) == 32
    assert snap.record_count == 0
    assert snap.created_at.tzinfo == UTC
    assert snap.label == ""
    assert snap.trigger == ""
    assert snap.size_bytes == 0


def test_memory_search_result_construction() -> None:
    record = MemoryRecord()
    result = MemorySearchResult(record=record)
    assert result.record is record
    assert result.score == 0.0
    assert result.dense_score == 0.0
    assert result.sparse_score == 0.0
    assert result.graph_score == 0.0
    assert result.rank == 0


def test_memory_search_result_scored() -> None:
    record = MemoryRecord()
    result = MemorySearchResult(
        record=record,
        score=0.87,
        dense_score=0.7,
        sparse_score=0.5,
        graph_score=0.3,
        rank=2,
    )
    assert result.score == 0.87
    assert result.dense_score == 0.7
    assert result.sparse_score == 0.5
    assert result.graph_score == 0.3
    assert result.rank == 2
