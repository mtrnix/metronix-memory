from metatron.core.models import Document, SyncResult
from metatron.ingestion import sync as sync_mod


class _StubStore:
    def __init__(self):
        self.upsert_calls = []
        self.mark_calls = []

    async def upsert_raw_documents(
        self, workspace_id, documents, connector_type, connection_id=None
    ):
        self.upsert_calls.append((workspace_id, connector_type, connection_id, documents))
        return {
            "new": len(documents),
            "updated": 0,
            "unchanged": 0,
            "changed_source_ids": [d.source_id for d in documents],
        }

    async def mark_documents_synced_by_source(
        self, workspace_id, connector_type, source_ids, target="qdrant"
    ):
        self.mark_calls.append((connector_type, source_ids, target))


async def test_persist_raw_documents_delegates_to_store():
    store = _StubStore()
    docs = [Document(source_id="a.txt", content="x", source_type="upload")]
    result = await sync_mod.persist_raw_documents(
        store, "ws_1", "upload", None, docs
    )
    assert result["changed_source_ids"] == ["a.txt"]
    assert store.upsert_calls[0][1] == "upload"
    assert store.upsert_calls[0][2] is None


async def test_sync_documents_to_stores_ingests_marks_and_graphs(monkeypatch):
    store = _StubStore()
    docs = [Document(source_id="a.txt", content="x", source_type="upload")]
    seen = {}

    async def fake_ingest(documents, workspace_id, connector_type, *, source_role, skip_graph, incremental):
        seen["ingest"] = dict(
            n=len(documents), ws=workspace_id, ct=connector_type,
            role=source_role, skip_graph=skip_graph, incremental=incremental,
        )
        return SyncResult(connector_type=connector_type, workspace_id=workspace_id,
                          documents_new=1, documents_updated=0, documents_skipped=0)

    async def fake_graphs(workspace_id, store):
        seen["graphs"] = workspace_id
        return {"ok": 1, "errors": 0}

    monkeypatch.setattr(sync_mod, "ingest_documents", fake_ingest)
    monkeypatch.setattr(sync_mod, "process_all_unsynced_graphs", fake_graphs)

    result = await sync_mod.sync_documents_to_stores(
        store, "ws_1", "upload", docs, source_role="user_upload", incremental=True
    )
    assert result.documents_new == 1
    assert seen["ingest"]["skip_graph"] is True
    assert seen["ingest"]["incremental"] is True
    assert seen["ingest"]["role"] == "user_upload"
    assert store.mark_calls[0] == ("upload", ["a.txt"], "qdrant")
    assert seen["graphs"] == "ws_1"
