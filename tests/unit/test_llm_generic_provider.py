"""Generic OpenAI-compatible LLM provider config (feat/llm-generic-provider).

Covers the LLM_PROVIDER_URL / LLM_PROVIDER_API_KEY / LLM_PROVIDER_MODEL vars and
their precedence over the legacy CUSTOM_LLM_* fallbacks.
"""

from metronix.core.config import Settings
from metronix.llm.provider import _settings_for_provider
from metronix.llm.providers.custom import CustomProvider


def test_generic_provider_defaults_empty() -> None:
    s = Settings()
    assert s.llm_provider_url == ""
    assert s.llm_provider_api_key == ""
    assert s.llm_provider_model == ""


def test_custom_mapping_prefers_generic_vars(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_PROVIDER_API_KEY", "generic-key")
    monkeypatch.setenv("LLM_PROVIDER_MODEL", "deepseek-chat")
    # Legacy vars present but must be overridden by the generic ones.
    monkeypatch.setenv("CUSTOM_LLM_URL", "http://legacy/v1")
    monkeypatch.setenv("CUSTOM_LLM_API_KEY", "legacy-key")
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "legacy-model")

    kwargs = _settings_for_provider("custom", Settings())
    assert kwargs["api_url"] == "https://api.deepseek.com/v1"
    assert kwargs["api_key"] == "generic-key"
    assert kwargs["model"] == "deepseek-chat"


def test_custom_mapping_falls_back_to_legacy(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_MODEL", raising=False)
    monkeypatch.setenv("CUSTOM_LLM_URL", "http://legacy/v1")
    monkeypatch.setenv("CUSTOM_LLM_API_KEY", "legacy-key")
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "legacy-model")

    kwargs = _settings_for_provider("custom", Settings())
    assert kwargs["api_url"] == "http://legacy/v1"
    assert kwargs["api_key"] == "legacy-key"
    assert kwargs["model"] == "legacy-model"


def test_unconfigured_url_is_not_available(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER_URL", raising=False)
    monkeypatch.delenv("CUSTOM_LLM_URL", raising=False)
    provider = CustomProvider(model="x", api_url="", api_key="")
    # Empty URL must stay empty, not become a bogus relative "/chat/completions".
    assert provider.api_url == ""
    assert provider.is_available() is False


def test_configured_url_gets_chat_completions_suffix() -> None:
    provider = CustomProvider(model="x", api_url="https://host/v1", api_key="k")
    assert provider.api_url == "https://host/v1/chat/completions"
    assert provider.is_available() is True


def test_default_model_prefers_generic_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER_MODEL", "deepseek-chat")
    monkeypatch.setenv("CUSTOM_LLM_MODEL", "legacy-model")
    assert CustomProvider(api_url="https://host/v1").default_model == "deepseek-chat"

    monkeypatch.delenv("LLM_PROVIDER_MODEL", raising=False)
    assert CustomProvider(api_url="https://host/v1").default_model == "legacy-model"
