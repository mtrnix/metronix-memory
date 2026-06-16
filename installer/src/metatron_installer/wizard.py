from __future__ import annotations

from typing import Protocol

from .config import InstallerConfig, LlmProvider, Mode, Profile, defaults_for
from .profiles import OPTIONAL_PROFILES, validate_profile_llm

_PROVIDERS_NEEDING_KEY = {LlmProvider.DEEPSEEK, LlmProvider.OPENROUTER, LlmProvider.CUSTOM}
_KEY_PROMPT = {
    LlmProvider.DEEPSEEK: "DeepSeek API key",
    LlmProvider.OPENROUTER: "OpenRouter API key",
    LlmProvider.CUSTOM: "Custom LLM API key",
}

# Profile choice labels shown to the user, keyed by enum value.
_PROFILE_LABELS: dict[Profile, str] = {
    Profile.MINIMAL: "minimal (core + metatron-ui :3000)",
    Profile.FULL: "full (core + ollama + all UIs :3000 :3001 :3080)",
    Profile.CUSTOM: "custom (pick individual services)",
}

# Deployment mode labels.
_MODE_LABELS: dict[Mode, str] = {
    Mode.SERVER: "server (bind 0.0.0.0, accessible from network)",
    Mode.LOCAL: "local (bind 127.0.0.1, localhost only)",
}

# Optional service labels for the custom profile checkbox.
_SERVICE_LABELS: dict[str, str] = {
    "ollama": "ollama (local LLM, port 11435)",
    "embedding-proxy": "embedding-proxy (embeddings proxy, port 8001)",
    "openwebui": "openwebui (chat UI, port 3080)",
    "ui": "ui (Metatron UI, port 3000)",
    "ui-cc": "ui-cc (Metatron UI CC, port 3001)",
}


def _pick_profile(prompter: Prompter) -> Profile:
    """Ask the user to pick a deployment profile with descriptions."""
    label_to_profile = {label: p for p, label in _PROFILE_LABELS.items()}
    choice = prompter.select("Deployment profile", list(label_to_profile.keys()))
    return label_to_profile[choice]


class Prompter(Protocol):
    def select(self, message: str, choices: list[str], default: str | None = None) -> str:
        """Prompt the user to pick one of ``choices``; return the chosen value."""

    def text(self, message: str, default: str = "") -> str:
        """Prompt for free text; return the entered value or ``default``."""

    def password(self, message: str) -> str:
        """Prompt for a hidden secret; return the entered value."""

    def confirm(self, message: str, default: bool = False) -> bool:
        """Prompt a yes/no question; return the boolean answer."""

    def checkbox(self, message: str, choices: list[str]) -> list[str]:
        """Prompt a multi-select over ``choices``; return the chosen subset."""


def run_wizard(prompter: Prompter) -> InstallerConfig:
    mode_labels = {label: m for m, label in _MODE_LABELS.items()}
    mode = mode_labels[prompter.select("Deployment mode", list(mode_labels.keys()))]
    provider = LlmProvider(prompter.select("LLM provider", [p.value for p in LlmProvider]))

    cfg = defaults_for(mode, Profile.MINIMAL)
    cfg.llm_provider = provider
    if provider in _PROVIDERS_NEEDING_KEY:
        cfg.llm_api_key = prompter.password(_KEY_PROMPT[provider])
    if provider is LlmProvider.CUSTOM:
        cfg.custom_llm_url = prompter.text(
            "Custom LLM URL", default="http://localhost:8080/v1"
        )

    profile = _pick_profile(prompter)
    cfg.profile = profile
    if profile is Profile.CUSTOM:
        label_to_service = {label: svc for svc, label in _SERVICE_LABELS.items()}
        chosen = prompter.checkbox(
            "Select optional services", list(label_to_service.keys())
        )
        cfg.enabled_profiles = [label_to_service[l] for l in chosen]

    # minimal + self-hosted ollama needs an external host.
    if provider is LlmProvider.OLLAMA and profile is Profile.MINIMAL:
        cfg.ollama_host = prompter.text("External Ollama host (http://host:11434)")
    validate_profile_llm(cfg.profile, cfg.llm_provider, cfg.ollama_host)

    if prompter.confirm("Configure optional integrations?", default=False):
        cfg.openai_compat_key = prompter.password("OpenAI-compat API key (blank to skip)")
        cfg.mcp_api_key = prompter.password("MCP API key (blank to skip)")
        cfg.telegram_bot_token = prompter.password("Telegram bot token (blank to skip)")

    return cfg
