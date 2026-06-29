"""Tests for agent memory exceptions (WS1)."""

from __future__ import annotations

import pytest

from metronix.core.exceptions import (
    AgentMemoryError,
    MemoryNotFoundError,
    MetronixError,
    SnapshotCorruptError,
)


def test_exception_hierarchy() -> None:
    assert issubclass(AgentMemoryError, MetronixError)
    assert issubclass(MemoryNotFoundError, AgentMemoryError)
    assert issubclass(SnapshotCorruptError, AgentMemoryError)


def test_memory_not_found_raise_catch() -> None:
    with pytest.raises(MemoryNotFoundError) as exc_info:
        raise MemoryNotFoundError("missing")
    # Catchable as either base class (except-clause matching is isinstance-based).
    assert isinstance(exc_info.value, AgentMemoryError)
    assert isinstance(exc_info.value, MetronixError)


def test_snapshot_corrupt_details() -> None:
    err = SnapshotCorruptError("hash mismatch", details={"expected": "abc", "got": "def"})
    assert err.details == {"expected": "abc", "got": "def"}
    assert str(err) == "hash mismatch"
