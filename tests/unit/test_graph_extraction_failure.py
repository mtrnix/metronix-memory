"""extract_graph_from_text: configurable NER timeout + raise-on-hard-failure.

A hard LLM failure (timeout / connection / 5xx) must propagate as an exception
so callers leave the document graph_synced=false and the sweep retries it —
rather than silently returning empty entities and marking the doc done, which
produced an empty knowledge graph for a sync that otherwise looked successful.
"""

from __future__ import annotations

import pytest

import metronix.storage.neo4j_graph as ng
from metronix.core.config import get_settings


def test_passes_configured_timeout_to_llm(monkeypatch):
    captured: dict = {}

    def _fake_chat_completion(*args, **kwargs):
        captured.update(kwargs)
        return '{"entities": [], "relationships": []}'

    monkeypatch.setattr(ng, "chat_completion", _fake_chat_completion)

    ng.extract_graph_from_text("Some document text about Qdrant and Neo4j.")

    assert captured["timeout"] == get_settings().graph_extraction_llm_timeout


def test_raises_on_hard_llm_failure(monkeypatch):
    # Never sleep between retries (keep the test fast).
    monkeypatch.setattr(ng.time, "sleep", lambda *_: None)

    def _always_fails(*args, **kwargs):
        raise RuntimeError("Ollama error: 500 Server Error")

    monkeypatch.setattr(ng, "chat_completion", _always_fails)

    with pytest.raises(RuntimeError, match="500 Server Error"):
        ng.extract_graph_from_text("Some document text.")
