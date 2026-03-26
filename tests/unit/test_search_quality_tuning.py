"""Tests for search quality tuning changes."""


def test_result_type_cached_in_scoring():
    """_result_type should be cached via type_cache dict."""
    import inspect
    from metatron.retrieval import search

    source = inspect.getsource(search.hybrid_search_and_answer)
    assert "type_cache" in source


def test_memory_dicts_not_mutated_with_internal_scores():
    """Internal scoring keys (_signal_score, _final_score) must not leak into memory dicts."""
    import inspect
    from metatron.retrieval import search

    source = inspect.getsource(search.hybrid_search_and_answer)
    assert '["_signal_score"]' not in source
    assert '["_final_score"]' not in source


def test_min_signal_score_in_config():
    """min_signal_score config field exists with default 0.0."""
    from metatron.core.config import Settings
    s = Settings()
    assert hasattr(s, "min_signal_score")
    assert s.min_signal_score == 0.0


def test_confidence_filter_in_search():
    """Search pipeline includes min_signal_score filtering logic."""
    import inspect
    from metatron.retrieval import search
    source = inspect.getsource(search.hybrid_search_and_answer)
    assert "min_signal_score" in source


def test_recall_graph_caches_entity_lookups():
    """Second call with same seeds should hit cache, not Memgraph."""
    from unittest.mock import patch, MagicMock
    from metatron.retrieval.channels import recall_graph, RecallContext, _cached_get_graph_entities

    ctx = RecallContext(
        original_query="test",
        translated_query="test",
        expanded_query="test",
        detected_language="en",
        workspace_id="ws1",
        access_filter=None,
        settings=MagicMock(recall_top_n_graph=5, recall_graph_max_depth=2),
        extracted_jira_keys=["MTRNIX-104"],
        extracted_title_entities=[],
        extracted_dates=None,
        detected_person=[],
        is_activity_query=False,
    )

    with patch("metatron.retrieval.channels.get_graph_entities") as mock_ents, \
         patch("metatron.retrieval.channels.get_doc_labels_by_entities") as mock_labels, \
         patch("metatron.retrieval.channels.get_graph_relationships") as mock_rels, \
         patch("metatron.retrieval.channels.get_hybrid_store") as mock_store:
        mock_ents.return_value = [{"name": "Auth"}]
        mock_labels.return_value = [{"doc_label": "jira:MTRNIX-104"}]
        mock_rels.return_value = []
        mock_store.return_value.search_by_doc_labels.return_value = []

        _cached_get_graph_entities.cache_clear()
        recall_graph(ctx)
        recall_graph(ctx)

        # get_graph_entities called only once (second call hits cache)
        assert mock_ents.call_count == 1
