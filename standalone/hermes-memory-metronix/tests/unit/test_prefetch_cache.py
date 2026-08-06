from __future__ import annotations

from metronix import MetronixMemoryProvider


def test_on_session_switch_updates_session_id_and_evicts_old_cache():
    provider = MetronixMemoryProvider()
    provider._session_id = "sess-old"
    provider._prefetch_cache = {"sess-old": "<memory-context>stale</memory-context>"}

    provider.on_session_switch("sess-new")

    assert provider._session_id == "sess-new"
    assert "sess-old" not in provider._prefetch_cache


def test_on_session_switch_ignores_empty_new_session_id():
    provider = MetronixMemoryProvider()
    provider._session_id = "sess-old"
    provider._prefetch_cache = {"sess-old": "<memory-context>stale</memory-context>"}

    provider.on_session_switch("")

    assert provider._session_id == "sess-old"
    assert provider._prefetch_cache == {"sess-old": "<memory-context>stale</memory-context>"}


def test_prefetch_falls_back_to_cached_session_id_when_not_passed():
    provider = MetronixMemoryProvider()
    provider._session_id = "sess-1"
    provider._prefetch_cache = {"sess-1": "<memory-context>hi</memory-context>"}

    assert provider.prefetch("anything") == "<memory-context>hi</memory-context>"
