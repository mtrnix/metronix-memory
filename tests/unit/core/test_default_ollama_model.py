"""Default local Ollama model is the small graph/NER model.

Asserts on the declared field defaults (env-independent) — the repo `.env`
may override the runtime value, but the code default is what we ship.
"""

from metronix.core.config import Settings


def test_default_ollama_llm_model_is_qwen() -> None:
    assert Settings.model_fields["ollama_llm_model"].default == "qwen2.5:3b"


def test_default_freshness_model_is_qwen() -> None:
    assert Settings.model_fields["freshness_llm_model"].default == "qwen2.5:3b"


def test_public_install_defaults_match_self_hosted_expectations() -> None:
    assert Settings.model_fields["freshness_enabled"].default is False
    assert Settings.model_fields["llm_telemetry_enabled"].default is False
    assert Settings.model_fields["cors_origins"].default == "*"


def test_ollama_chat_model_field_removed() -> None:
    # The redundant pull-only variable is gone.
    assert "ollama_chat_model" not in Settings.model_fields
