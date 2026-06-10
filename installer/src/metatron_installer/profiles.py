from __future__ import annotations

from .config import LlmProvider, Profile

# Optional compose profile names a user may toggle under CUSTOM.
OPTIONAL_PROFILES = ("ollama", "embedding-proxy", "openwebui")

# The services that FULL turns on, expressed as the single "full" compose profile.
FULL_PROFILE = "full"


class ProfileLlmError(ValueError):
    """Raised when a profile/LLM combination cannot work (e.g. minimal + self-hosted Ollama)."""


def compose_profiles_value(profile: Profile, custom_profiles: list[str]) -> str:
    """Return the COMPOSE_PROFILES env value for a profile selection."""
    if profile is Profile.MINIMAL:
        return ""
    if profile is Profile.FULL:
        return FULL_PROFILE
    return ",".join(sorted(set(custom_profiles)))


def validate_profile_llm(
    profile: Profile, provider: LlmProvider, ollama_host: str
) -> None:
    """minimal has no bundled Ollama; self-hosted ollama then needs an external host."""
    if provider is LlmProvider.OLLAMA and profile is Profile.MINIMAL and not ollama_host:
        raise ProfileLlmError(
            "Profile 'minimal' has no bundled Ollama. Choose profile 'full', "
            "or set an external Ollama host (OLLAMA_HOST)."
        )
