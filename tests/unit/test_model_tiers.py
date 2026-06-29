"""call_site -> model tier resolution (PROJ-397, A)."""

from __future__ import annotations

from types import SimpleNamespace

from metronix.llm.tiers import resolve_model_for_call_site


def _settings(provider="deepseek", heavy="deepseek-chat", fast=""):
    return SimpleNamespace(llm_provider=provider, deepseek_model=heavy, deepseek_model_fast=fast)


def test_fast_call_site_with_empty_fast_inherits_heavy() -> None:
    s = _settings(heavy="deepseek-chat", fast="")
    assert resolve_model_for_call_site("resolve_query", None, s) == "deepseek-chat"


def test_fast_call_site_with_custom_heavy_inherits_it() -> None:
    """Unset FAST + custom DEEPSEEK_MODEL => FAST inherits the custom heavy (AC: unset == identical)."""  # noqa: E501
    s = _settings(heavy="deepseek-custom-v9", fast="")
    assert resolve_model_for_call_site("query_classifier", None, s) == "deepseek-custom-v9"


def test_fast_call_site_uses_fast_when_set() -> None:
    s = _settings(heavy="deepseek-chat", fast="deepseek-flash")
    assert resolve_model_for_call_site("slot_extraction", None, s) == "deepseek-flash"


def test_heavy_call_site_returns_none() -> None:
    """rag_answer (and any non-FAST call_site) uses the provider default (None)."""
    s = _settings(fast="deepseek-flash")
    assert resolve_model_for_call_site("rag_answer", None, s) is None
    assert resolve_model_for_call_site("unknown_site", None, s) is None


def test_non_deepseek_provider_is_noop() -> None:
    s = _settings(provider="ollama", fast="deepseek-flash")
    assert resolve_model_for_call_site("resolve_query", None, s) is None


def test_explicit_model_always_wins() -> None:
    s = _settings(provider="deepseek", fast="deepseek-flash")
    assert resolve_model_for_call_site("resolve_query", "override-model", s) == "override-model"
    s2 = _settings(provider="ollama")
    assert resolve_model_for_call_site("rag_answer", "override-model", s2) == "override-model"
