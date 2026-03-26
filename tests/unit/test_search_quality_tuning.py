"""Tests for search quality tuning changes."""


def test_result_type_cached_in_scoring():
    """_result_type should be cached via type_cache dict."""
    import inspect
    from metatron.retrieval import search

    source = inspect.getsource(search.hybrid_search_and_answer)
    assert "type_cache" in source
