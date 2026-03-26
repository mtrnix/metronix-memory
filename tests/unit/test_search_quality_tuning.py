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
