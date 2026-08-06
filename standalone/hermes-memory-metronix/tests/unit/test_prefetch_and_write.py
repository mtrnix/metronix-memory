from __future__ import annotations

from metronix import MetronixMemoryProvider


class InlineThread:
    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def test_queue_prefetch_populates_cache_and_prefetch_reads_it(monkeypatch):
    provider = MetronixMemoryProvider()
    provider._config = {
        "prefetch": True,
        "prefetch_top_k": 8,
        "prefetch_types": ["preference", "pinned"],
        "cite_sources": True,
        "write_scope": "workspace",
    }
    provider._agent_id = "hermes"
    provider._session_id = "sess-1"

    class FakeClient:
        def search_memory(self, **kwargs):
            return [
                {"record": {"id": "a1", "kind": "fact", "content": "ignore me"}},
                {
                    "record": {
                        "id": "b2",
                        "kind": "preference",
                        "content": "User likes terse answers",
                    }
                },
                {"record": {"id": "c3", "kind": "pinned", "content": "Project codename is Atlas"}},
            ]

    provider._client = FakeClient()
    monkeypatch.setattr("metronix.threading.Thread", InlineThread)

    assert provider.prefetch("what do you know?", session_id="sess-1") == ""

    provider.queue_prefetch("what do you know?", session_id="sess-1")
    result = provider.prefetch("what do you know?", session_id="sess-1")

    assert "<memory-context>" in result
    assert "[b2] User likes terse answers" in result
    assert "[c3] Project codename is Atlas" in result
    assert "ignore me" not in result


def test_on_memory_write_posts_expected_payload(monkeypatch):
    provider = MetronixMemoryProvider()
    provider._config = {"write_through": True, "write_scope": "workspace"}
    provider._agent_id = "hermes"
    calls: list[dict] = []

    class FakeClient:
        def create_memory(self, **kwargs):
            calls.append(kwargs)
            return {"id": "mem-1"}

    provider._client = FakeClient()
    monkeypatch.setattr("metronix.threading.Thread", InlineThread)

    provider.on_memory_write("add", "user", "Prefers black coffee", metadata={"source": "test"})

    assert len(calls) == 1
    assert calls[0]["scope"] == "global"
    assert calls[0]["kind"] == "preference"
    assert calls[0]["source_type"] == "hermes_memory_write"
    assert calls[0]["tags"] == ["hermes", "user"]
    assert calls[0]["metadata"]["target"] == "user"
    assert calls[0]["metadata"]["source"] == "test"


def test_sync_turn_writes_session_records(monkeypatch):
    provider = MetronixMemoryProvider()
    provider._config = {"sync_turns": True}
    provider._agent_id = "hermes"
    provider._session_id = "sess-123"
    calls: list[dict] = []

    class FakeClient:
        def create_memory(self, **kwargs):
            calls.append(kwargs)
            return {"id": "mem"}

    provider._client = FakeClient()
    monkeypatch.setattr("metronix.threading.Thread", InlineThread)

    provider.sync_turn("hello", "world")

    assert len(calls) == 2
    assert calls[0]["scope"] == "session"
    assert calls[0]["session_id"] == "sess-123"
    assert calls[1]["scope"] == "session"
    assert calls[1]["metadata"]["role"] == "assistant"


def test_queue_prefetch_fail_open_invokes_warning_callback(monkeypatch):
    provider = MetronixMemoryProvider()
    provider._config = {"prefetch": True, "prefetch_top_k": 8, "prefetch_types": ["fact"]}
    provider._session_id = "sess-1"
    warnings: list[str] = []
    provider._warning_callback = warnings.append

    class BrokenClient:
        def search_memory(self, **kwargs):
            raise RuntimeError("boom")

    provider._client = BrokenClient()
    monkeypatch.setattr("metronix.threading.Thread", InlineThread)

    provider.queue_prefetch("test", session_id="sess-1")

    assert provider.prefetch("test", session_id="sess-1") == ""
    assert warnings
    assert "Metronix prefetch failed" in warnings[0]
