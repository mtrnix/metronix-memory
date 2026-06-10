from pathlib import Path

import pytest

from metatron_installer.answers import (
    AnswersError,
    load_answers_yaml,
    load_answers_yaml_text,
)
from metatron_installer.config import LlmProvider, Mode, Profile

FIX = Path(__file__).parent / "fixtures" / "answers_minimal.yaml"


def test_loads_minimal_yaml_into_config():
    cfg = load_answers_yaml(FIX)
    assert cfg.mode is Mode.SERVER
    assert cfg.profile is Profile.MINIMAL
    assert cfg.llm_provider is LlmProvider.DEEPSEEK
    assert cfg.llm_api_key == "sk-test-123"
    assert cfg.bind_host == "0.0.0.0"


def test_invalid_profile_raises():
    with pytest.raises(AnswersError):
        load_answers_yaml_text("mode: server\nprofile: nope\nllm_provider: deepseek\n")


def test_minimal_with_ollama_no_host_raises():
    text = "mode: server\nprofile: minimal\nllm_provider: ollama\nollama_host: ''\n"
    with pytest.raises(AnswersError):
        load_answers_yaml_text(text)
