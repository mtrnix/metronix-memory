import pytest

from metatron_installer.config import LlmProvider, Profile
from metatron_installer.profiles import (
    ProfileLlmError,
    compose_profiles_value,
    validate_profile_llm,
)


def test_minimal_has_no_optional_profiles():
    assert compose_profiles_value(Profile.MINIMAL, []) == ""


def test_full_enables_full_profile():
    assert compose_profiles_value(Profile.FULL, []) == "full"


def test_custom_joins_selected_profiles_sorted():
    val = compose_profiles_value(Profile.CUSTOM, ["openwebui", "ollama"])
    assert val == "ollama,openwebui"


def test_minimal_with_ollama_provider_and_no_external_host_is_error():
    with pytest.raises(ProfileLlmError):
        validate_profile_llm(Profile.MINIMAL, LlmProvider.OLLAMA, ollama_host="")


def test_minimal_with_ollama_provider_and_external_host_ok():
    validate_profile_llm(Profile.MINIMAL, LlmProvider.OLLAMA, ollama_host="http://10.0.0.5:11434")


def test_full_with_ollama_provider_ok_without_external_host():
    validate_profile_llm(Profile.FULL, LlmProvider.OLLAMA, ollama_host="")


def test_external_provider_never_errors():
    validate_profile_llm(Profile.MINIMAL, LlmProvider.DEEPSEEK, ollama_host="")
