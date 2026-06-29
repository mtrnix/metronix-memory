"""Unit tests for AsyncQdrantVectorStore.update_payload_by_doc_label (MTRNIX-313)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def async_store() -> object:
    """Build an AsyncQdrantVectorStore with a mocked client.

    ``__init__`` is skipped so no real AsyncQdrantClient is instantiated. We
    set the fields the method uses (``client``, ``collection_name``,
    ``workspace_id``) by hand.
    """
    from metronix.storage.qdrant import AsyncQdrantVectorStore

    store = AsyncQdrantVectorStore.__new__(AsyncQdrantVectorStore)
    store.workspace_id = "ws-1"
    store.collection_name = "metronix_ws_1"
    store.client = AsyncMock()
    store.client.set_payload = AsyncMock()
    store._collection_ensured = True
    return store


async def test_update_payload_calls_set_payload_with_doc_label_and_workspace_filter(
    async_store: object,
) -> None:
    await async_store.update_payload_by_doc_label(
        workspace_id="ws-1",
        doc_label="doc-42",
        payload={"status": "archived", "freshness_score": 0.0},
    )
    async_store.client.set_payload.assert_awaited_once()
    kwargs = async_store.client.set_payload.await_args.kwargs
    assert kwargs["payload"] == {"status": "archived", "freshness_score": 0.0}
    assert kwargs["wait"] is False
    assert kwargs["collection_name"] == "metronix_ws_1"
    # The filter selector must scope both by doc_label AND workspace_id so
    # a collision on doc_label across tenants does not leak.
    flt = kwargs["points"]
    conditions = {c.key for c in flt.must}
    assert conditions == {"doc_label", "workspace_id"}


async def test_update_payload_swallows_qdrant_errors(async_store: object) -> None:
    async_store.client.set_payload = AsyncMock(side_effect=RuntimeError("qdrant down"))
    # Must not raise — the freshness worker treats payload sync as best-effort.
    await async_store.update_payload_by_doc_label(
        workspace_id="ws-1",
        doc_label="doc-42",
        payload={"status": "archived"},
    )


async def test_update_payload_copies_dict_not_aliases(async_store: object) -> None:
    """Callers sometimes build a payload once and reuse it; mutating our copy
    must not alter the caller's."""
    original = {"status": "archived"}
    await async_store.update_payload_by_doc_label(
        workspace_id="ws-1",
        doc_label="doc-42",
        payload=original,
    )
    sent = async_store.client.set_payload.await_args.kwargs["payload"]
    assert sent == original
    assert sent is not original
