from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .config import InstallerConfig, LlmProvider
from .envfile import merge_env
from .profiles import compose_profiles_value
from .secrets import generate_fernet_key, generate_password

if TYPE_CHECKING:
    from collections.abc import Callable

    from .docker import CommandResult, DockerShell

# Which LLM providers write an API key into .env, and under which key.
_LLM_KEY_ENV = {
    LlmProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
    LlmProvider.OPENROUTER: "OPENROUTER_API_KEY",
    LlmProvider.CUSTOM: "CUSTOM_LLM_API_KEY",
}


def build_overrides(cfg: InstallerConfig) -> dict[str, str]:
    """The single place an InstallerConfig becomes .env keys. Auto-fills missing secrets."""
    fernet = cfg.fernet_key or generate_fernet_key()
    pg = cfg.postgres_password or generate_password()
    neo = cfg.neo4j_password or generate_password()

    overrides: dict[str, str] = {
        "METATRON_AUTOSYNC_ENABLED": "true",
        "FERNET_KEY": fernet,
        "POSTGRES_PASSWORD": pg,
        "NEO4J_PASSWORD": neo,
        "NEO4J_USER": "neo4j",
        "NEO4J_AUTH": f"neo4j/{neo}",
        "LLM_PROVIDER": cfg.llm_provider.value,
        "COMPOSE_PROFILES": compose_profiles_value(cfg.profile, cfg.enabled_profiles),
    }
    if cfg.llm_provider in _LLM_KEY_ENV and cfg.llm_api_key:
        overrides[_LLM_KEY_ENV[cfg.llm_provider]] = cfg.llm_api_key
    if cfg.ollama_host:
        overrides["OLLAMA_HOST"] = cfg.ollama_host
    if cfg.custom_llm_url:
        overrides["CUSTOM_LLM_URL"] = cfg.custom_llm_url
    for env_key, value in (
        ("METATRON_OPENAI_COMPAT_KEY", cfg.openai_compat_key),
        ("METATRON_MCP_API_KEY", cfg.mcp_api_key),
        ("TELEGRAM_BOT_TOKEN", cfg.telegram_bot_token),
        ("DISCORD_BOT_TOKEN", cfg.discord_bot_token),
        ("SLACK_BOT_TOKEN", cfg.slack_bot_token),
        ("SLACK_APP_TOKEN", cfg.slack_app_token),
    ):
        if value:
            overrides[env_key] = value
    return overrides


def render_artifacts(cfg: InstallerConfig, template: str) -> tuple[str, str]:
    """Return (.env text, COMPOSE_PROFILES value) without touching Docker."""
    overrides = build_overrides(cfg)
    env_text = merge_env(template, overrides)
    return env_text, overrides["COMPOSE_PROFILES"]


def launch_stack(
    shell: DockerShell,
    compose_file: str,
    compose_profiles: str,
    registry_login: Callable[[], CommandResult] | None,
) -> bool:
    env = dict(os.environ)
    env["COMPOSE_PROFILES"] = compose_profiles
    if not shell.compose_pull(compose_file, env, registry_login):
        return False
    return shell.compose_up(compose_file, env).returncode == 0
