"""``metronix_store`` must register the document in PG ``raw_documents``.

Originally the MCP store tool called ``ingest_documents`` directly, so an
MCP-ingested document never got a ``raw_documents`` row (no source-of-truth, no
freshness tracking, no qdrant/graph sync flags) — unlike connector and upload
docs. These tests pin the corrected behaviour: persist a raw_documents row, index
into Qdrant for this doc only, mark it qdrant-synced, and DEFER graph extraction
(graph_synced stays false for the batch graph sweeper).
"""

from __future__ import annotations

import metronix.ingestion.pipeline as pipeline_mod
import metronix.mcp.tools._source_deps as source_deps
from metronix.core.models import SyncResult


class _StubStore:
    """Captures the raw_documents lifecycle calls without touching a real DB."""

    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, object]] = []
        self.mark_calls: list[tuple[str, list[str], str]] = []

    async def upsert_raw_documents(
        self, workspace_id, documents, connector_type, connection_id=None
    ):
        self.upsert_calls.append(
            {
                "workspace_id": workspace_id,
                "connector_type": connector_type,
                "connection_id": connection_id,
                "documents": documents,
            }
        )
        return {
            "new": len(documents),
            "updated": 0,
            "unchanged": 0,
            "changed_source_ids": [d.source_id for d in documents],
        }

    async def mark_documents_synced_by_source(
        self, workspace_id, connector_type, source_ids, target="qdrant"
    ):
        self.mark_calls.append((connector_type, list(source_ids), target))


def _patch_common(monkeypatch) -> _StubStore:
    """Wire a stub store + fake ingest; return the stub for assertions."""
    store = _StubStore()

    async def _fake_ingest(
        documents, workspace_id, connector_type, *, source_role, skip_graph, incremental
    ):
        _fake_ingest.kwargs = {
            "source_role": source_role,
            "skip_graph": skip_graph,
            "incremental": incremental,
        }
        return SyncResult(
            connector_type=connector_type,
            workspace_id=workspace_id,
            documents_new=len(documents),
        )

    _fake_ingest.kwargs = {}

    async def _fake_graphs(workspace_id, store, **_kw):
        _fake_graphs.n += 1
        return {"ok": 0, "errors": 0}

    _fake_graphs.n = 0

    # Reuse the shared process-cached store (no fresh engine per call).
    monkeypatch.setattr(source_deps, "get_store", lambda: store)
    monkeypatch.setattr(pipeline_mod, "ingest_documents", _fake_ingest)
    # The whole-workspace graph pass must NOT run from the synchronous MCP path.
    monkeypatch.setattr(pipeline_mod, "process_all_unsynced_graphs", _fake_graphs)

    store._fake_ingest = _fake_ingest  # type: ignore[attr-defined]
    store._fake_graphs = _fake_graphs  # type: ignore[attr-defined]
    return store


async def test_metronix_store_persists_raw_document(monkeypatch):
    store = _patch_common(monkeypatch)

    from metronix.mcp.tools.store import metronix_store

    out = await metronix_store(
        content="hello world",
        title="Title",
        workspace_id="WS",
        doc_label="DOC-1",
    )

    assert "error" not in out, out
    assert out["success"] is True
    assert out["doc_label"] == "DOC-1"
    assert out["chunks_stored"] == 1

    # Phase 1: a raw_documents row is upserted as an unmanaged MCP source.
    assert len(store.upsert_calls) == 1
    call = store.upsert_calls[0]
    assert call["workspace_id"] == "WS"
    assert call["connector_type"] == "memory"
    assert call["connection_id"] is None
    doc = call["documents"][0]
    assert doc.source_id == "DOC-1"
    assert doc.source_role == "knowledge_base"
    assert doc.content == "hello world"

    # Indexing is scoped to THIS document, re-store is idempotent
    # (incremental=True), and graph extraction is deferred (skip_graph=True).
    assert store._fake_ingest.kwargs == {
        "source_role": "knowledge_base",
        "skip_graph": True,
        "incremental": True,
    }
    assert store._fake_graphs.n == 0, "graph extraction must not run in the synchronous MCP call"

    # Only the qdrant flag is marked; graph_synced stays false for the sweeper.
    assert store.mark_calls == [("memory", ["DOC-1"], "qdrant")]


async def test_metronix_store_rejects_whitespace_only_content(monkeypatch):
    store = _patch_common(monkeypatch)

    from metronix.mcp.tools.store import metronix_store

    out = await metronix_store(content="   \n\t ", doc_label="BLANK-1")

    # Whitespace-only must be rejected up front: no raw_documents row, no
    # qdrant-synced flag for a document with zero chunks.
    assert "error" in out
    assert store.upsert_calls == []
    assert store.mark_calls == []
