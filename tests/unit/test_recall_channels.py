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
        "settings": MagicMock(recall_top_n_dense=30, recall_top_n_exact=10, recall_top_n_metadata=10, recall_top_n_graph=5),
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
# recall_graph
# ---------------------------------------------------------------------------


@patch("metatron.retrieval.channels.get_hybrid_store")
@patch("metatron.retrieval.channels.get_doc_labels_by_entities")
@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_finds_related_docs(mock_get_ents, mock_get_labels, mock_store_fn):
    mock_get_ents.return_value = [{"name": "RBAC", "type": "concept"}]
    mock_get_labels.return_value = [
        {"doc_label": "DOC-1", "entity": "RBAC"},
        {"doc_label": "DOC-2", "entity": "RBAC"},
    ]
    store = MagicMock()
    mock_store_fn.return_value = store
    store.search_by_doc_labels.return_value = [
        {"id": "p1", "score": 0.8, "doc_label": "DOC-1", "memory": "t"},
        {"id": "p2", "score": 0.7, "doc_label": "DOC-2", "memory": "t"},
    ]
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5))
    results = recall_graph(ctx)
    assert len(results) == 2


@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_empty_when_no_entities(mock_get_ents):
    mock_get_ents.return_value = []
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5))
    results = recall_graph(ctx)
    assert results == []


@patch("metatron.retrieval.channels.get_graph_entities")
def test_recall_graph_graceful_on_error(mock_get_ents):
    mock_get_ents.side_effect = Exception("Memgraph down")
    ctx = _make_ctx(settings=MagicMock(recall_top_n_graph=5))
    results = recall_graph(ctx)
    assert results == []
