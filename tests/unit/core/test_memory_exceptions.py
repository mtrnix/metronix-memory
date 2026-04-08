"""Tests for agent memory exceptions (WS1)."""

from __future__ import annotations

import pytest

from metatron.core.exceptions import (
    AgentMemoryError,
    MemoryNotFoundError,
    MetatronError,
    SnapshotCorruptError,
)


def test_exception_hierarchy() -> None:
    assert issubclass(AgentMemoryError, MetatronError)
    assert issubclass(MemoryNotFoundError, AgentMemoryError)
    assert issubclass(SnapshotCorruptError, AgentMemoryError)


def test_memory_not_found_raise_catch() -> None:
    with pytest.raises(AgentMemoryError):
        raise MemoryNotFoundError("missing")
    with pytest.raises(MetatronError):
        raise MemoryNotFoundError("missing")


def test_snapshot_corrupt_details() -> None:
    err = SnapshotCorruptError("hash mismatch", details={"expected": "abc", "got": "def"})
    assert err.details == {"expected": "abc", "got": "def"}
    assert str(err) == "hash mismatch"
