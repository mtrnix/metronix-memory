"""Freshness filter pushdown — integration smoke (MTRNIX-313).

Exercises the ``_build_freshness_filter`` + ``_combine_filters`` path with a
real Qdrant collection: upsert two chunks (one ARCHIVED payload, one
ACTIVE), run a ``hybrid_search`` with the filter both off and on, and
assert the ARCHIVED chunk is excluded when the flag flips.

This is a narrow integration smoke, not a full search_and_answer run. It
catches payload-filter regressions without standing up the whole LLM
pipeline.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from metronix.core.config import get_settings
from metronix.retrieval.channels import _combine_filters
from metronix.retrieval.search import _build_freshness_filter
from metronix.storage.qdrant import AsyncQdrantVectorStore

pytestmark = pytest.mark.integration


async def _seed_chunk(
    store: AsyncQdrantVectorStore,
    *,
    doc_label: str,
    status: str,
    content: str,
) -> None:
    """Upsert a single chunk with a minimal payload carrying ``status``."""
    from qdrant_client.models import PointStruct

    # Reuse the store's dense embed path so the vector is the right shape
    # and fits the existing collection config.
    from metronix.llm.embeddings import get_cached_embedding

    embedding = get_cached_embedding(content)
    point = PointStruct(
        id=uuid4().hex,
        vector={"dense": embedding},
        payload={
            "doc_label": doc_label,
            "workspace_id": store.workspace_id,
            "status": status,
            "data": content,
            "memory": content,
            "title": doc_label,
        },
    )
    await store._ensure_collection()
    await store.client.upsert(
        collection_name=store.collection_name,
        points=[point],
        wait=True,
    )


async def _cleanup(store: AsyncQdrantVectorStore, doc_labels: list[str]) -> None:
    import contextlib

    from qdrant_client.models import FieldCondition, Filter, MatchAny

    with contextlib.suppress(Exception):
        await store.client.delete(
            collection_name=store.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="doc_label", match=MatchAny(any=doc_labels))]
            ),
            wait=True,
        )


async def test_filter_off_returns_both_docs_filter_on_excludes_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    workspace = f"kbsearch-it-{uuid4().hex[:8]}"
    archived_label = f"archived-{uuid4().hex[:6]}"
    active_label = f"active-{uuid4().hex[:6]}"

    store = AsyncQdrantVectorStore(
        workspace_id=workspace,
        host=settings.qdrant_host,
        port=settings.qdrant_http_port,
        api_key=settings.qdrant_api_key or None,
        https=settings.qdrant_https,
    )

    try:
        await _seed_chunk(
            store,
            doc_label=archived_label,
            status="archived",
            content="Stripe webhook integration — deprecated endpoint.",
        )
        await _seed_chunk(
            store,
            doc_label=active_label,
            status="active",
            content="Stripe webhook integration — current endpoint.",
        )

        query = "Stripe webhook integration"

        # --- Filter OFF: both docs should appear ---
        monkeypatch.setattr(settings, "freshness_kb_search_filter_enabled", False)
        off_filter = _build_freshness_filter(settings)
        assert off_filter is None
        hits_off = await store.hybrid_search(
            query, limit=10, filter_conditions=_combine_filters(None, off_filter)
        )
        labels_off = {h.get("doc_label") for h in hits_off}
        assert archived_label in labels_off
        assert active_label in labels_off

        # --- Filter ON: archived doc excluded ---
        monkeypatch.setattr(settings, "freshness_kb_search_filter_enabled", True)
        on_filter = _build_freshness_filter(settings)
        assert on_filter is not None
        hits_on = await store.hybrid_search(
            query, limit=10, filter_conditions=_combine_filters(None, on_filter)
        )
        labels_on = {h.get("doc_label") for h in hits_on}
        assert archived_label not in labels_on
        assert active_label in labels_on
    finally:
        import contextlib

        await _cleanup(store, [archived_label, active_label])
        with contextlib.suppress(Exception):
            await store.client.delete_collection(collection_name=store.collection_name)
        with contextlib.suppress(Exception):
            await store.client.close()
