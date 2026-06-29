"""Tests for agent memory event constants (WS1)."""

from __future__ import annotations

import re

from metronix.core.events import (
    MEMORY_DELETED,
    MEMORY_RESET,
    MEMORY_RESTORED,
    MEMORY_SNAPSHOT_CREATED,
    MEMORY_STORED,
)


def test_memory_event_constants_distinct() -> None:
    constants = [
        MEMORY_STORED,
        MEMORY_DELETED,
        MEMORY_RESET,
        MEMORY_SNAPSHOT_CREATED,
        MEMORY_RESTORED,
    ]
    assert all(isinstance(c, str) for c in constants)
    assert len(set(constants)) == 5


def test_memory_event_constants_snake_case() -> None:
    pattern = re.compile(r"^memory_[a-z_]+$")
    for c in (
        MEMORY_STORED,
        MEMORY_DELETED,
        MEMORY_RESET,
        MEMORY_SNAPSHOT_CREATED,
        MEMORY_RESTORED,
    ):
        assert pattern.match(c), c
