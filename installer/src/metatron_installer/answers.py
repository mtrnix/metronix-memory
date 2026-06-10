from __future__ import annotations

from pathlib import Path

import yaml

from .config import InstallerConfig, LlmProvider, Mode, Profile, defaults_for
from .profiles import ProfileLlmError, validate_profile_llm


class AnswersError(ValueError):
    """Invalid or inconsistent non-interactive answers file."""


def load_answers_yaml(path: str | Path) -> InstallerConfig:
    return load_answers_yaml_text(Path(path).read_text())


def load_answers_yaml_text(text: str) -> InstallerConfig:
    data = yaml.safe_load(text) or {}
    try:
        mode = Mode(data.get("mode", "server"))
        profile = Profile(data.get("profile", "minimal"))
        provider = LlmProvider(data.get("llm_provider", "deepseek"))
    except ValueError as exc:
        raise AnswersError(str(exc)) from exc

    cfg = defaults_for(mode, profile)
    cfg.llm_provider = provider
    cfg.llm_api_key = data.get("llm_api_key", "")
    cfg.ollama_host = data.get("ollama_host", "") or ""
    integrations = data.get("integrations") or {}
    cfg.openai_compat_key = integrations.get("openai_compat_key", "")
    cfg.mcp_api_key = integrations.get("mcp_api_key", "")
    cfg.telegram_bot_token = integrations.get("telegram_bot_token", "")
    cfg.discord_bot_token = integrations.get("discord_bot_token", "")
    cfg.slack_bot_token = integrations.get("slack_bot_token", "")
    cfg.slack_app_token = integrations.get("slack_app_token", "")
    cfg.enabled_profiles = list(data.get("enabled_profiles") or [])
    registry = data.get("registry") or {}
    cfg.github_user = registry.get("github_user", "")
    cfg.github_token = registry.get("github_token", "")

    try:
        validate_profile_llm(cfg.profile, cfg.llm_provider, cfg.ollama_host)
    except ProfileLlmError as exc:
        raise AnswersError(str(exc)) from exc
    return cfg
