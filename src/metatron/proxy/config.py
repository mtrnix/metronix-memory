"""UpstreamConfig — parses AgentRecord.current_config['upstream']."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Provider = Literal[
    "openai", "openrouter", "vllm", "ollama", "deepseek_oai", "litellm", "custom_oai"
]

# Default OpenAI-compatible base URLs per provider. custom_oai/vllm/litellm have
# no canonical default — base_url must be supplied explicitly for those.
_DEFAULT_BASE_URL: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek_oai": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
}


class UpstreamConfig(BaseModel):
    """Per-agent upstream LLM configuration."""

    model_config = ConfigDict(extra="ignore")

    provider: Provider
    model_name: str
    base_url: str | None = None
    api_key_ref: str | None = None
    params: dict[str, Any] = {}

    def resolved_base_url(self) -> str:
        """Explicit base_url wins; else provider default; else raise."""
        if self.base_url:
            return self.base_url.rstrip("/")
        default = _DEFAULT_BASE_URL.get(self.provider)
        if default is None:
            msg = f"base_url required for provider {self.provider!r}"
            raise ValueError(msg)
        return default


def parse_upstream_config(current_config: dict[str, Any]) -> UpstreamConfig | None:
    """Return UpstreamConfig from current_config['upstream'] or None if absent."""
    raw = current_config.get("upstream")
    if not raw:
        return None
    return UpstreamConfig.model_validate(raw)
