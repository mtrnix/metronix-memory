"""Graph extraction failure handling: configurable timeout, typed give-up, parking.

A hard LLM failure (timeout / connection / 5xx) raises GraphExtractionError so
callers park the document as graph_failed (terminal) instead of silently
returning empty entities or retrying it forever.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import metronix.ingestion.pipeline as pipeline
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


def test_default_timeout_is_300() -> None:
    from metronix.core.config import Settings

    assert Settings.model_fields["graph_extraction_llm_timeout"].default == 300


def test_raises_graph_extraction_error_on_hard_failure(monkeypatch):
    monkeypatch.setattr(ng.time, "sleep", lambda *_: None)

    def _always_fails(*args, **kwargs):
        raise RuntimeError("Ollama error: 500 Server Error")

    monkeypatch.setattr(ng, "chat_completion", _always_fails)

    with pytest.raises(ng.GraphExtractionError, match="500 Server Error"):
        ng.extract_graph_from_text("Some document text.")


async def test_process_unsynced_graphs_parks_failed_doc(monkeypatch):
    """A GraphExtractionError parks the doc as graph_failed and does NOT mark it synced."""
    store = AsyncMock()
    store.get_unsynced_documents = AsyncMock(
        return_value=[
            {
                "connector_type": "confluence",
                "source_id": "doc1",
                "title": "T",
                "content": "non-empty content",
                "url": "",
                "author": "",
                "metadata": {},
            }
        ]
    )
    store.mark_documents_synced_by_source = AsyncMock()
    store.mark_documents_graph_failed = AsyncMock()

    monkeypatch.setattr(ng, "close_graph_driver", lambda: None)

    def _raise_extraction_error(*args, **kwargs):
        raise ng.GraphExtractionError("Ollama error: timeout")

    monkeypatch.setattr(pipeline, "_write_graph_strict", _raise_extraction_error)

    result = await pipeline.process_unsynced_graphs("MTRNIX", store, batch_size=10)

    assert result["errors"] == 1
    store.mark_documents_graph_failed.assert_awaited_once()
    # The doc must NOT be marked graph_synced when extraction gave up.
    store.mark_documents_synced_by_source.assert_not_awaited()
