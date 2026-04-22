"""RawDocumentTarget adapter tests (MTRNIX-313)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import LifecycleStatus, RawDocument
from metatron.ingestion.freshness.target_raw_document import RawDocumentTarget


async def test_target_identity() -> None:
    t = RawDocumentTarget(pg_store=MagicMock(), qdrant_factory=MagicMock())
    assert t.kind == "raw_document"
    assert t.supports_candidate_promotion is False


async def test_get_returns_freshness_target_record() -> None:
    pg = MagicMock()
    pg.get_raw_document_by_id = AsyncMock(
        return_value=RawDocument(
            id="doc-1",
            workspace_id="ws",
            title="t",
            content="body",
            status=LifecycleStatus.ACTIVE,
        )
    )
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=MagicMock())

    rec = await t.get("ws", "doc-1")

    assert rec is not None
    assert rec.target_id == "doc-1"
    assert rec.content == "body"
    assert rec.status is LifecycleStatus.ACTIVE
    # Raw documents carry no agent_id.
    assert rec.agent_id is None


async def test_get_returns_none_when_row_missing() -> None:
    pg = MagicMock()
    pg.get_raw_document_by_id = AsyncMock(return_value=None)
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=MagicMock())

    rec = await t.get("ws", "missing")

    assert rec is None


async def test_similarity_search_dedups_by_doc_label() -> None:
    pg = MagicMock()
    qdrant = MagicMock()
    # hybrid_search returns per-chunk hits; multiple chunks of the same doc
    # must collapse into one SimilarityHit.
    qdrant.hybrid_search = AsyncMock(
        return_value=[
            {"payload": {"doc_label": "doc-2", "content": "c1"}, "score": 0.9},
            {"payload": {"doc_label": "doc-2", "content": "c2"}, "score": 0.8},
            {"payload": {"doc_label": "doc-3", "content": "c3"}, "score": 0.7},
        ]
    )
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=lambda _ws: qdrant)

    hits = await t.similarity_search("ws", "query", top_k=10)

    assert [h.target_id for h in hits] == ["doc-2", "doc-3"]
    # Top score wins per doc.
    assert hits[0].score == 0.9


async def test_similarity_search_respects_top_k() -> None:
    pg = MagicMock()
    qdrant = MagicMock()
    qdrant.hybrid_search = AsyncMock(
        return_value=[
            {"payload": {"doc_label": f"d{i}"}, "score": 0.9 - i * 0.01} for i in range(10)
        ]
    )
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=lambda _ws: qdrant)

    hits = await t.similarity_search("ws", "q", top_k=3)

    assert len(hits) == 3


async def test_update_lifecycle_forwards_to_pg() -> None:
    pg = MagicMock()
    pg.update_raw_document_lifecycle = AsyncMock()
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=MagicMock())

    await t.update_lifecycle(
        "ws",
        "doc-1",
        status=LifecycleStatus.STALE,
        freshness_score=0.25,
    )

    pg.update_raw_document_lifecycle.assert_awaited_once()
    kwargs = pg.update_raw_document_lifecycle.await_args.kwargs
    assert kwargs["status"] is LifecycleStatus.STALE
    assert kwargs["freshness_score"] == 0.25


async def test_update_lifecycle_ignores_append_tag() -> None:
    """raw_documents has no tags column — ``append_tag`` must be silently dropped."""
    pg = MagicMock()
    pg.update_raw_document_lifecycle = AsyncMock()
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=MagicMock())

    await t.update_lifecycle("ws", "doc-1", append_tag="auto_curated")

    pg.update_raw_document_lifecycle.assert_awaited_once()
    kwargs = pg.update_raw_document_lifecycle.await_args.kwargs
    assert "append_tag" not in kwargs


async def test_sync_downstream_stores_writes_qdrant_payload() -> None:
    qdrant = MagicMock()
    qdrant.update_payload_by_doc_label = AsyncMock()
    t = RawDocumentTarget(pg_store=MagicMock(), qdrant_factory=lambda _ws: qdrant)

    await t.sync_downstream_stores(
        "ws",
        "doc-1",
        status=LifecycleStatus.ARCHIVED,
        freshness_score=0.0,
    )

    qdrant.update_payload_by_doc_label.assert_awaited_once_with(
        workspace_id="ws",
        doc_label="doc-1",
        payload={"status": "archived", "freshness_score": 0.0},
    )


async def test_sync_downstream_stores_swallows_qdrant_errors() -> None:
    qdrant = MagicMock()
    qdrant.update_payload_by_doc_label = AsyncMock(side_effect=RuntimeError("qdrant down"))
    t = RawDocumentTarget(pg_store=MagicMock(), qdrant_factory=lambda _ws: qdrant)

    # Must not raise — best-effort invariant.
    await t.sync_downstream_stores(
        "ws",
        "doc-1",
        status=LifecycleStatus.ARCHIVED,
        freshness_score=0.0,
    )


@pytest.mark.parametrize("edges", [[], [("d2", 0.9)]])
async def test_link_edges_batch_best_effort(edges: list) -> None:
    pg = MagicMock()
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=MagicMock())

    # Empty batch is a no-op; non-empty with Neo4j errors is swallowed.
    from unittest.mock import patch

    with patch(
        "metatron.storage.raw_document_graph.link_raw_documents_batch",
        side_effect=RuntimeError("neo4j down"),
    ):
        await t.link_edges_batch("ws", "doc-1", edges)
