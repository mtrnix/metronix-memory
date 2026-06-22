from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Mode(StrEnum):
    SERVER = "server"
    LOCAL = "local"


class Profile(StrEnum):
    MINIMAL = "minimal"
    FULL = "full"
    CUSTOM = "custom"


class LlmProvider(StrEnum):
    OLLAMA = "ollama"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    CUSTOM = "custom"


@dataclass
class InstallerConfig:
    mode: Mode = Mode.SERVER
    profile: Profile = Profile.MINIMAL
    bind_host: str = "0.0.0.0"
    llm_provider: LlmProvider = LlmProvider.DEEPSEEK
    llm_api_key: str = ""
    # Custom provider endpoint (required when llm_provider=custom).
    custom_llm_url: str = ""
    # External embeddings endpoint, required when profile=minimal (no bundled Ollama).
    ollama_host: str = ""
    # Secrets (auto-generated if empty at render time).
    fernet_key: str = ""
    postgres_password: str = ""
    neo4j_password: str = ""
    # Optional integrations.
    openai_compat_key: str = ""
    mcp_api_key: str = ""
    telegram_bot_token: str = ""
    discord_bot_token: str = ""
    slack_bot_token: str = ""
    slack_app_token: str = ""
    # Custom-profile service toggles (compose profile names).
    enabled_profiles: list[str] = field(default_factory=list)
    # Registry auth (filled only if anonymous pull fails).
    github_user: str = ""
    github_token: str = ""

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["mode"] = self.mode.value
        d["profile"] = self.profile.value
        d["llm_provider"] = self.llm_provider.value
        return d


def defaults_for(mode: Mode, profile: Profile) -> InstallerConfig:
    return InstallerConfig(
        mode=mode,
        profile=profile,
        bind_host="0.0.0.0" if mode is Mode.SERVER else "127.0.0.1",
        llm_provider=LlmProvider.DEEPSEEK,
    )
