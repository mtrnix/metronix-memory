from __future__ import annotations

from .config import LlmProvider, Profile

# Optional compose profile names a user may toggle under CUSTOM.
OPTIONAL_PROFILES = ("ollama", "embedding-proxy", "openwebui", "ui", "ui-cc")

# The services that FULL turns on, expressed as the single "full" compose profile.
FULL_PROFILE = "full"

# The services that MINIMAL turns on — just the core UI.
MINIMAL_PROFILE = "ui"

# Map of compose profile name → (label, url) for UI endpoints.
_UI_URLS: dict[str, tuple[str, str]] = {
    "ui": ("Metatron UI", "http://localhost:3000"),
    "ui-cc": ("Metatron UI CC", "http://localhost:3001"),
    "openwebui": ("Open WebUI", "http://localhost:3080"),
}


def ui_urls(compose_profiles: str) -> list[tuple[str, str]]:
    """Return (label, url) for each UI active in *compose_profiles*."""
    if not compose_profiles:
        return []
    active = set(compose_profiles.split(","))
    return [info for profile, info in _UI_URLS.items() if profile in active]


class ProfileLlmError(ValueError):
    """Raised when a profile/LLM combination cannot work (e.g. minimal + self-hosted Ollama)."""


def compose_profiles_value(profile: Profile, custom_profiles: list[str]) -> str:
    """Return the COMPOSE_PROFILES env value for a profile selection."""
    if profile is Profile.MINIMAL:
        return MINIMAL_PROFILE
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
