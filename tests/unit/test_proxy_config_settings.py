"""Proxy Settings fields (PROJ-372 P1)."""

from metronix.core.config import Settings


def test_proxy_defaults() -> None:
    s = Settings()
    assert s.proxy_enabled is False  # default OFF until integration gate passes (W3)
    assert s.proxy_query_rewrite_enabled is False
    assert s.proxy_tool_result_enrichment is True
    assert s.proxy_query_rewrite_timeout_ms == 400
    assert s.proxy_memory_search_timeout_ms == 800
    assert s.proxy_knowledge_search_timeout_ms == 800
    assert s.proxy_tool_result_enrichment_timeout_ms == 500
    assert s.proxy_upstream_timeout_ms == 120000
    assert s.proxy_knowledge_top_k == 5
    assert s.proxy_entity_trie_ttl_seconds == 600
    assert s.proxy_entity_trie_max_entities_per_ws == 50000
    assert s.proxy_default_upstream_key == ""


def test_proxy_env_override(monkeypatch) -> None:
    monkeypatch.setenv("METRONIX_PROXY_ENABLED", "false")
    monkeypatch.setenv("METRONIX_PROXY_KNOWLEDGE_TOP_K", "9")
    s = Settings()
    assert s.proxy_enabled is False
    assert s.proxy_knowledge_top_k == 9
