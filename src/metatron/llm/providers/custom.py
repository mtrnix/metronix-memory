"""Custom LLM provider for self-hosted OpenAI-compatible APIs.

Works with any server that implements the OpenAI chat completions API,
such as vLLM, text-generation-webui, LocalAI, etc.
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
    LLMResponse,
    Message,
)

logger = structlog.get_logger()


class CustomProvider(LLMProvider):
    """Custom OpenAI-compatible API provider."""

    name = "custom"

    def __init__(
        self,
        model: str | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize Custom provider.

        Args:
            model: Model name (server-specific).
            api_url: Full URL to chat completions endpoint.
            api_key: Optional API key for authentication.
        """
        super().__init__(model, **kwargs)
        base_url = api_url or os.getenv("CUSTOM_LLM_URL", "")
        # Ensure URL points to chat completions endpoint
        self.api_url = (
            base_url if base_url.endswith("/chat/completions")
            else f"{base_url.rstrip('/')}/chat/completions"
        )
        self.api_key = api_key or os.getenv("CUSTOM_LLM_API_KEY", "")

    @property
    def default_model(self) -> str:
        return os.getenv("CUSTOM_LLM_MODEL", "default")

    def is_available(self) -> bool:
        """Check if custom API endpoint is configured."""
        return bool(self.api_url)

    def chat_completion(  # TODO: async migration
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
        timeout: int = 60,
        **kwargs,
    ) -> LLMResponse:
        """Send chat completion request to custom API."""
        if not self.api_url:
            raise LLMConnectionError("CUSTOM_LLM_URL not configured")

        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

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
                self.api_url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if resp.status_code == 401:
                raise LLMAuthenticationError("Custom API authentication failed")

            if resp.status_code >= 400:
                logger.error(
                    "custom_api.error_response",
                    status=resp.status_code,
                    body=resp.text[:500],
                    model=self.model,
                )

            resp.raise_for_status()
            data = resp.json()

            # Handle OpenAI-compatible response format
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
            raise LLMConnectionError(f"Custom API timeout after {timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to custom API at {self.api_url}: {e}")
        except requests.exceptions.HTTPError as e:
            raise LLMError(f"Custom API error: {e}")
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected response format from custom API: {e}")
