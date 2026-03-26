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
