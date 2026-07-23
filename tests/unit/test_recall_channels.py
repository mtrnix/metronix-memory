from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metronix.retrieval.channels import (
    RecallContext,
    ScoredResult,
    merge_channels,
    recall_dense,
    recall_exact,
    recall_graph,
    recall_graph_ppr_async,
    recall_metadata,
)


def _make_ctx(**overrides) -> RecallContext:
    """Helper to build RecallContext with sensible defaults."""
    defaults = {
        "original_query": "test query",
        "translated_query": "test query",
        "expanded_query": "test query expanded",
        "detected_language": "en",
        "workspace_id": "TEST",
        "access_filter": None,
        "settings": MagicMock(
            recall_top_n_dense=30,
            recall_top_n_exact=10,
            recall_top_n_metadata=10,
            recall_top_n_graph=5,
            recall_graph_max_depth=2,
            adaptive_rrf_enabled=False,
        ),
        "extracted_jira_keys": [],
        "extracted_title_entities": [],
        "extracted_dates": None,
        "detected_person": [],
        "is_activity_query": False,
    }
    defaults.update(overrides)
    return RecallContext(**defaults)


def test_recall_context_creation():
    ctx = _make_ctx(
        original_query="What is PROJ-104?",
        extracted_jira_keys=["PROJ-104"],
    )
    assert ctx.original_query == "What is PROJ-104?"
    assert ctx.extracted_jira_keys == ["PROJ-104"]
    assert ctx.is_activity_query is False
    assert ctx.detected_person == []


@pytest.mark.asyncio
@patch("metronix.retrieval.channels.get_async_hybrid_store", new_callable=AsyncMock)
@patch("metronix.retrieval.channels.get_ppr_subgraph")
@patch("metronix.retrieval.channels.resolve_entity_aliases_batch")
@patch("metronix.retrieval.channels.get_entities_by_doc_labels")
async def test_ppr_recall_uses_entities_from_dense_document_labels(
    mock_entities: MagicMock,
    mock_aliases: MagicMock,
    mock_subgraph: MagicMock,
    mock_store_factory: AsyncMock,
) -> None:
    mock_entities.return_value = [{"name": "Qdrant"}]
    mock_aliases.return_value = {"Qdrant": {"Qdrant"}}
    mock_subgraph.return_value = (
        {"entity:qdrant": None, "document:guide": "DOC-GUIDE"},
        [("entity:qdrant", "document:guide", 1.0)],
    )
    store = MagicMock()
    store.search_by_doc_labels = AsyncMock(
        return_value=[{"id": "chunk-guide", "doc_label": "DOC-GUIDE", "memory": {}}]
    )
    mock_store_factory.return_value = store
    ctx = _make_ctx(
        settings=MagicMock(
            recall_top_n_graph=5,
            retrieval_graph_ppr_dense_anchor_count=5,
            retrieval_graph_ppr_alpha=0.85,
            retrieval_graph_ppr_max_iterations=30,
            retrieval_graph_ppr_tolerance=1e-6,
            retrieval_graph_ppr_max_nodes=500,
        )
    )
    dense = [
        {
            "chunk_id": "dense-1",
            "doc_label": "DOC-ANCHOR",
            "score": 0.9,
            "memory": {},
            "channel": "dense",
        }
    ]

    results = await recall_graph_ppr_async(ctx, dense)

    assert [(item["doc_label"], item["channel"]) for item in results] == [("DOC-GUIDE", "graph")]
    assert results[0]["score"] > 0.0
    mock_entities.assert_called_once_with(["DOC-ANCHOR"], workspace_id="TEST")
    mock_subgraph.assert_called_once_with(["Qdrant"], workspace_id="TEST", max_nodes=500)


@pytest.mark.asyncio
@patch("metronix.retrieval.channels.get_ppr_subgraph", side_effect=RuntimeError("graph down"))
@patch(
    "metronix.retrieval.channels.resolve_entity_aliases_batch",
    return_value={"Qdrant": {"Qdrant"}},
)
async def test_ppr_recall_degrades_to_empty_results_on_graph_failure(
    mock_aliases: MagicMock, mock_subgraph: MagicMock
) -> None:
    ctx = _make_ctx(
        extracted_title_entities=["Qdrant"],
        settings=MagicMock(
            recall_top_n_graph=5,
            retrieval_graph_ppr_dense_anchor_count=5,
            retrieval_graph_ppr_alpha=0.85,
            retrieval_graph_ppr_max_iterations=30,
            retrieval_graph_ppr_tolerance=1e-6,
            retrieval_graph_ppr_max_nodes=500,
        ),
    )

    assert await recall_graph_ppr_async(ctx, []) == []
    mock_aliases.assert_called_once()
    mock_subgraph.assert_called_once()


def test_scored_result_is_typed_dict():
    result: ScoredResult = {
        "chunk_id": "abc-123",
        "doc_label": "PROJ-104",
        "score": 0.85,
        "memory": {"title": "RBAC impl", "text": "...", "type": "jira"},
    }
    assert result["chunk_id"] == "abc-123"
    assert result["doc_label"] == "PROJ-104"
    assert result["score"] == 0.85


def test_merge_deduplicates_by_chunk_id():
    """Same chunk from two channels — both channel scores preserved, max used for ordering."""
    ch1 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.8, "memory": {}, "channel": "dense"}]
    ch2 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.9, "memory": {}, "channel": "exact"}]
    merged = merge_channels([ch1, ch2])
    assert len(merged) == 1
    assert max(merged[0]["channel_scores"].values()) == 0.9
    assert set(merged[0]["channels"]) == {"dense", "exact"}


def test_merge_preserves_multiple_chunks_same_doc():
    """Different chunks from same doc — both kept."""
    ch1 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.8, "memory": {}, "channel": "dense"}]
    ch2 = [{"chunk_id": "b", "doc_label": "DOC-1", "score": 0.7, "memory": {}, "channel": "dense"}]
    merged = merge_channels([ch1, ch2])
    assert len(merged) == 2


def test_merge_sorts_by_score_descending():
    ch1 = [{"chunk_id": "a", "doc_label": "D1", "score": 0.5, "memory": {}, "channel": "dense"}]
    ch2 = [{"chunk_id": "b", "doc_label": "D2", "score": 0.9, "memory": {}, "channel": "dense"}]
    ch3 = [{"chunk_id": "c", "doc_label": "D3", "score": 0.7, "memory": {}, "channel": "dense"}]
    merged = merge_channels([ch1, ch2, ch3])
    max_scores = [max(r["channel_scores"].values()) for r in merged]
    assert max_scores == [0.9, 0.7, 0.5]


def test_merge_handles_empty_channels():
    ch1 = [{"chunk_id": "a", "doc_label": "D1", "score": 0.8, "memory": {}, "channel": "dense"}]
    merged = merge_channels([ch1, [], [], []])
    assert len(merged) == 1


def test_merge_all_empty():
    merged = merge_channels([[], [], [], []])
    assert merged == []


# ---------------------------------------------------------------------------
# TestMergeChannelsMultiSignal — merge_channels preserves channel info
# ---------------------------------------------------------------------------


class TestMergeChannelsMultiSignal:
    """merge_channels preserves channel info in MergedResult."""

    def test_single_channel(self) -> None:
        results = [
            [
                ScoredResult(
                    chunk_id="c1", doc_label="D1", score=0.9, memory={"m": "t"}, channel="dense"
                ),
            ]
        ]
        merged = merge_channels(results)
        assert len(merged) == 1
        assert merged[0]["channels"] == ["dense"]
        assert merged[0]["channel_scores"] == {"dense": 0.9}

    def test_same_chunk_two_channels(self) -> None:
        results = [
            [
                ScoredResult(
                    chunk_id="c1", doc_label="D1", score=0.9, memory={"m": "t"}, channel="dense"
                )
            ],
            [
                ScoredResult(
                    chunk_id="c1", doc_label="D1", score=0.6, memory={"m": "t"}, channel="graph"
                )
            ],
        ]
        merged = merge_channels(results)
        assert len(merged) == 1
        assert set(merged[0]["channels"]) == {"dense", "graph"}
        assert merged[0]["channel_scores"]["dense"] == 0.9
        assert merged[0]["channel_scores"]["graph"] == 0.6

    def test_sorted_by_max_channel_score(self) -> None:
        results = [
            [ScoredResult(chunk_id="c1", doc_label="D1", score=0.5, memory={}, channel="dense")],
            [ScoredResult(chunk_id="c2", doc_label="D2", score=0.9, memory={}, channel="exact")],
        ]
        merged = merge_channels(results)
        assert merged[0]["chunk_id"] == "c2"

    def test_memory_from_highest_scoring_channel(self) -> None:
        results = [
            [
                ScoredResult(
                    chunk_id="c1",
                    doc_label="D1",
                    score=0.5,
                    memory={"src": "dense"},
                    channel="dense",
                )
            ],
            [
                ScoredResult(
                    chunk_id="c1",
                    doc_label="D1",
                    score=0.9,
                    memory={"src": "exact"},
                    channel="exact",
                )
            ],
        ]
        merged = merge_channels(results)
        assert merged[0]["memory"]["src"] == "exact"

    def test_empty_input(self) -> None:
        assert merge_channels([]) == []
        assert merge_channels([[], []]) == []


# ---------------------------------------------------------------------------
# recall_dense
# ---------------------------------------------------------------------------


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_dense_calls_hybrid_search(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.hybrid_search.return_value = [
        {"id": "p1", "score": 0.9, "doc_label": "DOC-1", "title": "T1", "memory": "text1"},
        {"id": "p2", "score": 0.7, "doc_label": "DOC-2", "title": "T2", "memory": "text2"},
    ]
    ctx = _make_ctx()
    results = recall_dense(ctx)
    store.hybrid_search.assert_called_once()
    assert len(results) == 2
    assert results[0]["chunk_id"] == "p1"
    assert results[0]["doc_label"] == "DOC-1"


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_dense_respects_limit(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.hybrid_search.return_value = [
        {"id": f"p{i}", "score": 1.0 - i * 0.1, "doc_label": f"D{i}", "memory": f"t{i}"}
        for i in range(10)
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_dense=5))
    results = recall_dense(ctx)
    assert len(results) <= 5


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_dense_graceful_on_error(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.hybrid_search.side_effect = Exception("Qdrant down")
    ctx = _make_ctx()
    results = recall_dense(ctx)
    assert results == []


# ---------------------------------------------------------------------------
# recall_exact
# ---------------------------------------------------------------------------


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_exact_jira_keys(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 1.0, "doc_label": "PROJ-104", "memory": "rbac"},
    ]
    store.scroll_by_title.return_value = []
    ctx = _make_ctx(extracted_jira_keys=["PROJ-104"], settings=MagicMock(recall_top_n_exact=10))
    results = recall_exact(ctx)
    store.search_by_doc_labels.assert_called_once_with(["PROJ-104"])
    assert len(results) == 1
    assert results[0]["doc_label"] == "PROJ-104"


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_exact_title_entities(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = []
    store.scroll_by_title.return_value = [
        {"id": "p2", "score": 0.8, "doc_label": "DOC-1", "memory": "aurora"},
    ]
    ctx = _make_ctx(
        extracted_title_entities=["Project Aurora"], settings=MagicMock(recall_top_n_exact=10)
    )
    results = recall_exact(ctx)
    assert len(results) >= 1


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_exact_empty_when_no_keys_no_entities(mock_store_fn):
    ctx = _make_ctx(settings=MagicMock(recall_top_n_exact=10))
    results = recall_exact(ctx)
    assert results == []


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_exact_graceful_on_error(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.side_effect = Exception("Qdrant down")
    ctx = _make_ctx(extracted_jira_keys=["PROJ-1"], settings=MagicMock(recall_top_n_exact=10))
    results = recall_exact(ctx)
    assert results == []


# ---------------------------------------------------------------------------
# recall_metadata
# ---------------------------------------------------------------------------


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_metadata_date_filter(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_date.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "D1", "memory": "t"},
    ]
    ctx = _make_ctx(
        extracted_dates=("2026-03-01", "2026-03-31"), settings=MagicMock(recall_top_n_metadata=10)
    )
    results = recall_metadata(ctx)
    assert len(results) == 1


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_metadata_person_query(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_assignee.return_value = [
        {"id": "p1", "score": 0.9, "doc_label": "D1", "memory": "t"},
    ]
    ctx = _make_ctx(detected_person=["John Smith"], settings=MagicMock(recall_top_n_metadata=10))
    results = recall_metadata(ctx)
    store.search_by_assignee.assert_called()
    assert len(results) >= 1


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_metadata_activity_query(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_status.return_value = [
        {"id": "p1", "score": 0.7, "doc_label": "D1", "memory": "t"},
    ]
    ctx = _make_ctx(is_activity_query=True, settings=MagicMock(recall_top_n_metadata=10))
    recall_metadata(ctx)
    store.search_by_status.assert_called()


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_metadata_person_skips_status(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_assignee.return_value = []
    ctx = _make_ctx(
        detected_person=["John Smith"],
        is_activity_query=True,
        settings=MagicMock(recall_top_n_metadata=10),
    )
    recall_metadata(ctx)
    store.search_by_assignee.assert_called()
    store.search_by_status.assert_not_called()


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_metadata_empty_when_nothing_detected(mock_store_fn):
    ctx = _make_ctx(settings=MagicMock(recall_top_n_metadata=10))
    results = recall_metadata(ctx)
    assert results == []


@patch("metronix.retrieval.channels.get_hybrid_store")
def test_recall_metadata_graceful_on_error(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_date.side_effect = Exception("Qdrant down")
    ctx = _make_ctx(
        extracted_dates=("2026-03-01", "2026-03-31"), settings=MagicMock(recall_top_n_metadata=10)
    )
    results = recall_metadata(ctx)
    assert results == []


# ---------------------------------------------------------------------------
# recall_graph (enhanced: seed collection + BFS hop expansion)
# ---------------------------------------------------------------------------


@patch("metronix.retrieval.channels.get_hybrid_store")
@patch("metronix.retrieval.channels.get_graph_relationships")
@patch("metronix.retrieval.channels.get_doc_labels_by_entities")
@patch("metronix.retrieval.channels.get_graph_entities")
def test_recall_graph_collects_seeds_from_all_sources(
    mock_get_ents,
    mock_get_labels,
    mock_get_rels,
    mock_store_fn,
):
    """Seeds come from jira keys, title entities, person names, and graph match."""
    mock_get_ents.return_value = [{"name": "RBAC", "type": "concept"}]
    mock_get_labels.side_effect = [
        [{"doc_label": "DOC-1", "entity": "RBAC"}],
        [{"doc_label": "DOC-3", "entity": "Auth"}],
    ]
    mock_get_rels.return_value = [
        {"source": "RBAC", "target": "Auth", "type": "RELATED_TO"},
    ]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "DOC-1", "memory": "t"},
        {"id": "p3", "score": 0.6, "doc_label": "DOC-3", "memory": "t"},
    ]
    ctx = _make_ctx(
        extracted_jira_keys=["PROJ-104"],
        extracted_title_entities=["Project Aurora"],
        detected_person=["John Smith"],
        settings=MagicMock(recall_top_n_graph=10, recall_graph_max_depth=1),
    )
    results = recall_graph(ctx)
    first_call_args = mock_get_labels.call_args_list[0]
    seed_names = set(first_call_args[0][0])
    assert "PROJ-104" in seed_names
    assert "Project Aurora" in seed_names
    assert "John Smith" in seed_names
    assert "RBAC" in seed_names
    assert len(results) >= 1


@patch("metronix.retrieval.channels.get_hybrid_store")
@patch("metronix.retrieval.channels.get_graph_relationships")
@patch("metronix.retrieval.channels.get_doc_labels_by_entities")
@patch("metronix.retrieval.channels.get_graph_entities")
def test_recall_graph_hop_expansion(mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn):
    """BFS hop expansion discovers entities at depth > 1."""
    mock_get_ents.return_value = [{"name": "A"}]
    mock_get_labels.side_effect = [
        [{"doc_label": "DOC-A"}],
        [{"doc_label": "DOC-B"}],
        [{"doc_label": "DOC-C"}],
    ]
    mock_get_rels.side_effect = [
        [{"source": "A", "target": "B", "type": "KNOWS"}],
        [{"source": "B", "target": "C", "type": "KNOWS"}],
    ]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.9, "doc_label": "DOC-A", "memory": "t"},
        {"id": "p2", "score": 0.8, "doc_label": "DOC-B", "memory": "t"},
        {"id": "p3", "score": 0.7, "doc_label": "DOC-C", "memory": "t"},
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=10, recall_graph_max_depth=2))
    recall_graph(ctx)
    call_args = store.search_by_doc_labels.call_args
    searched_labels = set(call_args[0][0])
    assert "DOC-A" in searched_labels
    assert "DOC-B" in searched_labels
    assert "DOC-C" in searched_labels


@patch("metronix.retrieval.channels.get_hybrid_store")
@patch("metronix.retrieval.channels.get_graph_relationships")
@patch("metronix.retrieval.channels.get_doc_labels_by_entities")
@patch("metronix.retrieval.channels.get_graph_entities")
def test_recall_graph_zero_depth_skips_expansion(
    mock_get_ents,
    mock_get_labels,
    mock_get_rels,
    mock_store_fn,
):
    """max_depth=0 means no hop expansion, only direct seed labels."""
    mock_get_ents.return_value = [{"name": "X"}]
    mock_get_labels.return_value = [{"doc_label": "DOC-X"}]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "DOC-X", "memory": "t"},
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=0))
    results = recall_graph(ctx)
    mock_get_rels.assert_not_called()
    assert len(results) == 1


@patch("metronix.retrieval.channels.get_graph_relationships")
@patch("metronix.retrieval.channels.get_doc_labels_by_entities")
@patch("metronix.retrieval.channels.get_graph_entities")
def test_recall_graph_empty_when_no_seeds(mock_get_ents, mock_get_labels, mock_get_rels):
    """No seeds from any source -> empty result, no graph calls."""
    mock_get_ents.return_value = []
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2))
    results = recall_graph(ctx)
    assert results == []
    mock_get_labels.assert_not_called()
    mock_get_rels.assert_not_called()


@patch("metronix.retrieval.channels.get_graph_entities")
def test_recall_graph_graceful_on_error(mock_get_ents):
    """Exception in graph calls -> empty result, no crash."""
    mock_get_ents.side_effect = Exception("Memgraph down")
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2))
    results = recall_graph(ctx)
    assert results == []


@patch("metronix.retrieval.channels.get_hybrid_store")
@patch("metronix.retrieval.channels.get_graph_relationships")
@patch("metronix.retrieval.channels.get_doc_labels_by_entities")
@patch("metronix.retrieval.channels.get_graph_entities")
def test_recall_graph_deduplicates_labels(
    mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn
):
    """Same doc_label from seeds and expansion -> fetched only once."""
    mock_get_ents.return_value = [{"name": "A"}]
    mock_get_labels.side_effect = [
        [{"doc_label": "DOC-1"}],
        [{"doc_label": "DOC-1"}],
    ]
    mock_get_rels.return_value = [{"source": "A", "target": "B", "type": "REL"}]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "DOC-1", "memory": "t"},
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=10, recall_graph_max_depth=1))
    recall_graph(ctx)
    searched_labels = store.search_by_doc_labels.call_args[0][0]
    assert len(searched_labels) == len(set(searched_labels)), "Labels should be deduplicated"


# ---------------------------------------------------------------------------
# TestChannelField — each recall function tags results with its channel name
# ---------------------------------------------------------------------------


class TestChannelField:
    """Each recall function tags results with its channel name."""

    @patch("metronix.retrieval.channels.get_hybrid_store")
    def test_recall_dense_sets_channel(self, mock_store) -> None:
        store = MagicMock()
        store.hybrid_search.return_value = [
            {"id": "1", "doc_label": "DOC-1", "score": 0.9, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx()
        results = recall_dense(ctx)
        assert len(results) == 1
        assert results[0]["channel"] == "dense"

    @patch("metronix.retrieval.channels.get_hybrid_store")
    def test_recall_exact_sets_channel(self, mock_store) -> None:
        store = MagicMock()
        store.search_by_doc_labels.return_value = [
            {"id": "1", "doc_label": "PROJ-1", "score": 0.9, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx(extracted_jira_keys=["PROJ-1"])
        results = recall_exact(ctx)
        assert len(results) >= 1
        assert all(r["channel"] == "exact" for r in results)

    @patch("metronix.retrieval.channels.get_hybrid_store")
    def test_recall_metadata_sets_channel(self, mock_store) -> None:
        store = MagicMock()
        store.search_by_date.return_value = [
            {"id": "1", "doc_label": "DOC-1", "score": 0.5, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx(extracted_dates=("2025-01-01", "2025-12-31"))
        results = recall_metadata(ctx)
        assert len(results) >= 1
        assert all(r["channel"] == "metadata" for r in results)

    @patch("metronix.retrieval.channels.get_graph_entities", return_value=[{"name": "Qdrant"}])
    @patch(
        "metronix.retrieval.channels.get_doc_labels_by_entities",
        return_value=[{"doc_label": "DOC-1"}],
    )
    @patch("metronix.retrieval.channels.get_graph_relationships", return_value=[])
    @patch("metronix.retrieval.channels.get_hybrid_store")
    def test_recall_graph_sets_channel(self, mock_store, _rels, _labels, _ents) -> None:
        store = MagicMock()
        store.search_by_doc_labels.return_value = [
            {"id": "1", "doc_label": "DOC-1", "score": 0.7, "memory": "text"},
        ]
        mock_store.return_value = store
        ctx = _make_ctx()
        results = recall_graph(ctx)
        assert len(results) >= 1
        assert all(r["channel"] == "graph" for r in results)
