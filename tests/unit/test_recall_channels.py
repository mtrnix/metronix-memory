from unittest.mock import MagicMock, patch

from metatron.retrieval.channels import (
    RecallContext,
    ScoredResult,
    merge_channels,
    recall_dense,
    recall_exact,
    recall_graph,
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
        "settings": MagicMock(recall_top_n_dense=30, recall_top_n_exact=10, recall_top_n_metadata=10, recall_top_n_graph=5, recall_graph_max_depth=2),
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
        original_query="What is MTRNIX-104?",
        extracted_jira_keys=["MTRNIX-104"],
    )
    assert ctx.original_query == "What is MTRNIX-104?"
    assert ctx.extracted_jira_keys == ["MTRNIX-104"]
    assert ctx.is_activity_query is False
    assert ctx.detected_person == []


def test_scored_result_is_typed_dict():
    result: ScoredResult = {
        "chunk_id": "abc-123",
        "doc_label": "MTRNIX-104",
        "score": 0.85,
        "memory": {"title": "RBAC impl", "text": "...", "type": "jira"},
    }
    assert result["chunk_id"] == "abc-123"
    assert result["doc_label"] == "MTRNIX-104"
    assert result["score"] == 0.85


def test_merge_deduplicates_by_chunk_id():
    """Same chunk from two channels — keep max score."""
    ch1 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.8, "memory": {}}]
    ch2 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.9, "memory": {}}]
    merged = merge_channels([ch1, ch2])
    assert len(merged) == 1
    assert merged[0]["score"] == 0.9


def test_merge_preserves_multiple_chunks_same_doc():
    """Different chunks from same doc — both kept."""
    ch1 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.8, "memory": {}}]
    ch2 = [{"chunk_id": "b", "doc_label": "DOC-1", "score": 0.7, "memory": {}}]
    merged = merge_channels([ch1, ch2])
    assert len(merged) == 2


def test_merge_sorts_by_score_descending():
    ch1 = [{"chunk_id": "a", "doc_label": "D1", "score": 0.5, "memory": {}}]
    ch2 = [{"chunk_id": "b", "doc_label": "D2", "score": 0.9, "memory": {}}]
    ch3 = [{"chunk_id": "c", "doc_label": "D3", "score": 0.7, "memory": {}}]
    merged = merge_channels([ch1, ch2, ch3])
    scores = [r["score"] for r in merged]
    assert scores == [0.9, 0.7, 0.5]


def test_merge_handles_empty_channels():
    ch1 = [{"chunk_id": "a", "doc_label": "D1", "score": 0.8, "memory": {}}]
    merged = merge_channels([ch1, [], [], []])
    assert len(merged) == 1


def test_merge_all_empty():
    merged = merge_channels([[], [], [], []])
    assert merged == []


# ---------------------------------------------------------------------------
# recall_dense
# ---------------------------------------------------------------------------


@patch("metatron.retrieval.channels.get_hybrid_store")
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


@patch("metatron.retrieval.channels.get_hybrid_store")
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


@patch("metatron.retrieval.channels.get_hybrid_store")
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


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_exact_jira_keys(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 1.0, "doc_label": "MTRNIX-104", "memory": "rbac"},
    ]
    store.scroll_by_title.return_value = []
    ctx = _make_ctx(extracted_jira_keys=["MTRNIX-104"], settings=MagicMock(recall_top_n_exact=10))
    results = recall_exact(ctx)
    store.search_by_doc_labels.assert_called_once_with(["MTRNIX-104"])
    assert len(results) == 1
    assert results[0]["doc_label"] == "MTRNIX-104"


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_exact_title_entities(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = []
    store.scroll_by_title.return_value = [
        {"id": "p2", "score": 0.8, "doc_label": "DOC-1", "memory": "aurora"},
    ]
    ctx = _make_ctx(extracted_title_entities=["Project Aurora"], settings=MagicMock(recall_top_n_exact=10))
    results = recall_exact(ctx)
    assert len(results) >= 1


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_exact_empty_when_no_keys_no_entities(mock_store_fn):
    ctx = _make_ctx(settings=MagicMock(recall_top_n_exact=10))
    results = recall_exact(ctx)
    assert results == []


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_exact_graceful_on_error(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.side_effect = Exception("Qdrant down")
    ctx = _make_ctx(extracted_jira_keys=["MTRNIX-1"], settings=MagicMock(recall_top_n_exact=10))
    results = recall_exact(ctx)
    assert results == []


# ---------------------------------------------------------------------------
# recall_metadata
# ---------------------------------------------------------------------------


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_metadata_date_filter(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_date.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "D1", "memory": "t"},
    ]
    ctx = _make_ctx(extracted_dates=("2026-03-01", "2026-03-31"), settings=MagicMock(recall_top_n_metadata=10))
    results = recall_metadata(ctx)
    assert len(results) == 1


@patch("metatron.retrieval.channels.get_hybrid_store")
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


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_metadata_activity_query(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_status.return_value = [
        {"id": "p1", "score": 0.7, "doc_label": "D1", "memory": "t"},
    ]
    ctx = _make_ctx(is_activity_query=True, settings=MagicMock(recall_top_n_metadata=10))
    results = recall_metadata(ctx)
    store.search_by_status.assert_called()


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_metadata_person_skips_status(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_assignee.return_value = []
    ctx = _make_ctx(detected_person=["John Smith"], is_activity_query=True, settings=MagicMock(recall_top_n_metadata=10))
    recall_metadata(ctx)
    store.search_by_assignee.assert_called()
    store.search_by_status.assert_not_called()


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_metadata_empty_when_nothing_detected(mock_store_fn):
    ctx = _make_ctx(settings=MagicMock(recall_top_n_metadata=10))
    results = recall_metadata(ctx)
    assert results == []


@patch("metatron.retrieval.channels.get_hybrid_store")
def test_recall_metadata_graceful_on_error(mock_store_fn):
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_date.side_effect = Exception("Qdrant down")
    ctx = _make_ctx(extracted_dates=("2026-03-01", "2026-03-31"), settings=MagicMock(recall_top_n_metadata=10))
    results = recall_metadata(ctx)
    assert results == []


# ---------------------------------------------------------------------------
# recall_graph (enhanced: seed collection + BFS hop expansion)
# ---------------------------------------------------------------------------


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_collects_seeds_from_all_sources(
    mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn,
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
        extracted_jira_keys=["MTRNIX-104"],
        extracted_title_entities=["Project Aurora"],
        detected_person=["John Smith"],
        settings=MagicMock(recall_top_n_graph=10, recall_graph_max_depth=1),
    )
    results = recall_graph(ctx)
    first_call_args = mock_get_labels.call_args_list[0]
    seed_names = set(first_call_args[0][0])
    assert "MTRNIX-104" in seed_names
    assert "Project Aurora" in seed_names
    assert "John Smith" in seed_names
    assert "RBAC" in seed_names
    assert len(results) >= 1


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
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
    results = recall_graph(ctx)
    call_args = store.search_by_doc_labels.call_args
    searched_labels = set(call_args[0][0])
    assert "DOC-A" in searched_labels
    assert "DOC-B" in searched_labels
    assert "DOC-C" in searched_labels


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_zero_depth_skips_expansion(
    mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn,
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


@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_empty_when_no_seeds(mock_get_ents, mock_get_labels, mock_get_rels):
    """No seeds from any source -> empty result, no graph calls."""
    mock_get_ents.return_value = []
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2))
    results = recall_graph(ctx)
    assert results == []
    mock_get_labels.assert_not_called()
    mock_get_rels.assert_not_called()


@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_graceful_on_error(mock_get_ents):
    """Exception in graph calls -> empty result, no crash."""
    mock_get_ents.side_effect = Exception("Memgraph down")
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2))
    results = recall_graph(ctx)
    assert results == []


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_graph_relationships")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_deduplicates_labels(mock_get_ents, mock_get_labels, mock_get_rels, mock_store_fn):
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
    results = recall_graph(ctx)
    searched_labels = store.search_by_doc_labels.call_args[0][0]
    assert len(searched_labels) == len(set(searched_labels)), "Labels should be deduplicated"
