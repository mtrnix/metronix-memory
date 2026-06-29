"""Settings.model_for_provider() — provider -> model-name resolution."""

from metronix.core.config import Settings


def test_ollama_maps_to_ollama_llm_model() -> None:
    s = Settings(LLM_PROVIDER="ollama", OLLAMA_LLM_MODEL="qwen2.5:3b")
    assert s.model_for_provider("ollama") == "qwen2.5:3b"


def test_deepseek_maps_to_deepseek_model() -> None:
    s = Settings(DEEPSEEK_MODEL="deepseek-chat")
    assert s.model_for_provider("deepseek") == "deepseek-chat"


def test_unknown_provider_returns_empty_string() -> None:
    s = Settings()
    assert s.model_for_provider("nope") == ""
