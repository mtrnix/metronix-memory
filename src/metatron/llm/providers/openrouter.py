"""OpenRouter LLM provider implementation.

OpenRouter provides access to multiple models (Claude, GPT, Llama, etc.)
through a unified API.
"""

import os

import requests
import structlog

from metatron.core.http import get_http_session
from metatron.llm.base import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    Message,
)

logger = structlog.get_logger()


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider - access multiple models via one API."""

    name = "openrouter"
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize OpenRouter provider.

        Args:
            model: Model name (e.g., "anthropic/claude-3-haiku").
            api_key: API key (falls back to OPENROUTER_API_KEY env var).
        """
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.site_url = kwargs.get("site_url", os.getenv("OPENROUTER_SITE_URL", ""))
        self.app_name = kwargs.get("app_name", os.getenv("OPENROUTER_APP_NAME", "Metatron"))

    @property
    def default_model(self) -> str:
        return os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")

    def is_available(self) -> bool:
        """Check if OpenRouter API is configured."""
        return bool(self.api_key)

    def chat_completion(  # TODO: async migration
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
        timeout: int = 60,
        **kwargs,
    ) -> LLMResponse:
        """Send chat completion request to OpenRouter API."""
        if not self.api_key:
            raise LLMAuthenticationError("OPENROUTER_API_KEY not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
        }

        payload = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            session = get_http_session()
            resp = session.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if resp.status_code == 401:
                raise LLMAuthenticationError("Invalid OpenRouter API key")
            if resp.status_code == 429:
                raise LLMRateLimitError("OpenRouter rate limit exceeded")
            if resp.status_code == 404:
                error_detail = resp.text[:500] if resp.text else "No details"
                raise LLMError(
                    f"OpenRouter model '{self.model}' not found. Details: {error_detail}"
                )

            if resp.status_code == 400:
                error_detail = resp.text[:500] if resp.text else "No details"
                # If json_mode was requested, retry without it
                if (
                    json_mode
                    and "response_format" in error_detail.lower()
                    or "json" in error_detail.lower()
                ):
                    payload.pop("response_format", None)
                    resp = session.post(
                        self.API_URL,
                        headers=headers,
                        json=payload,
                        timeout=timeout,
                    )
                    if resp.status_code != 200:
                        raise LLMError(
                            f"OpenRouter error (retry without json_mode): {resp.text[:300]}"
                        )
                else:
                    raise LLMError(f"OpenRouter bad request: {error_detail}")

            resp.raise_for_status()
            data = resp.json()

            # Check for error in response body
            if "error" in data:
                error_msg = data["error"].get("message", str(data["error"]))
                raise LLMError(f"OpenRouter error: {error_msg}")

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            return LLMResponse(
                content=content.strip(),
                model=self.model,
                provider=self.name,
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                raw_response=data,
            )

        except requests.exceptions.Timeout:
            raise LLMConnectionError(f"OpenRouter API timeout after {timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to OpenRouter API: {e}")
        except requests.exceptions.HTTPError as e:
            raise LLMError(f"OpenRouter API error: {e}")
