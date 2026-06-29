"""AssemblyTimeouts.from_settings (PROJ-372 P2)."""

from metronix.core.config import Settings
from metronix.memory.assembly_timeouts import AssemblyTimeouts


def test_from_settings_maps_ms() -> None:
    s = Settings()
    t = AssemblyTimeouts.from_settings(s)
    assert t.query_rewrite_ms == 400
    assert t.memories_ms == 800
    assert t.knowledge_ms == 800


def test_seconds_helpers() -> None:
    t = AssemblyTimeouts(query_rewrite_ms=400, memories_ms=800, knowledge_ms=1000)
    assert t.memories_s == 0.8
    assert t.knowledge_s == 1.0
    assert t.query_rewrite_s == 0.4
