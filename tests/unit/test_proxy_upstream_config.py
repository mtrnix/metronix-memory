"""UpstreamConfig parsing (PROJ-372 P1)."""

import pytest
from pydantic import ValidationError

from metronix.proxy.config import UpstreamConfig, parse_upstream_config


def test_minimal_valid() -> None:
    cfg = UpstreamConfig.model_validate({"provider": "openai", "model_name": "gpt-4o-mini"})
    assert cfg.provider == "openai"
    assert cfg.model_name == "gpt-4o-mini"
    assert cfg.api_key_ref is None
    assert cfg.params == {}
    assert cfg.resolved_base_url() == "https://api.openai.com/v1"


def test_explicit_base_url_wins() -> None:
    cfg = UpstreamConfig.model_validate(
        {"provider": "custom_oai", "model_name": "m", "base_url": "http://x/v1"}
    )
    assert cfg.resolved_base_url() == "http://x/v1"


def test_invalid_provider_rejected() -> None:
    with pytest.raises(ValidationError):
        UpstreamConfig.model_validate({"provider": "nope", "model_name": "m"})


def test_parse_from_current_config_missing_returns_none() -> None:
    assert parse_upstream_config({}) is None
    assert parse_upstream_config({"upstream": None}) is None


def test_parse_from_current_config_ok() -> None:
    cfg = parse_upstream_config({"upstream": {"provider": "openrouter", "model_name": "x"}})
    assert cfg is not None
    assert cfg.provider == "openrouter"
