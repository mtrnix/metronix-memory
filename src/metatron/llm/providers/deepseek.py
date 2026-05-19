"""DeepSeek LLM provider implementation."""

import os
import time

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


class DeepSeekProvider(LLMProvider):
    """DeepSeek API provider."""

    name = "deepseek"
    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize DeepSeek provider.

        Args:
            model: Model name (default: deepseek-chat).
            api_key: API key (falls back to DEEPSEEK_API_KEY env var).
        """
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")

    @property
    def default_model(self) -> str:
        return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def is_available(self) -> bool:
        """Check if DeepSeek API is configured."""
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
        """Send chat completion request to DeepSeek API."""
        if not self.api_key:
            raise LLMAuthenticationError("DEEPSEEK_API_KEY not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
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

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                session = get_http_session()
                resp = session.post(
                    self.API_URL,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )

                if resp.status_code == 401:
                    raise LLMAuthenticationError("Invalid DeepSeek API key")
                if resp.status_code == 429:
                    raise LLMRateLimitError("DeepSeek rate limit exceeded")

                resp.raise_for_status()
                data = resp.json()

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
                last_error = LLMConnectionError(f"DeepSeek API timeout after {timeout}s")
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
                last_error = LLMConnectionError(f"DeepSeek connection error: {e}")
            except requests.exceptions.HTTPError as e:
                raise LLMError(f"DeepSeek API error: {e}")
            except Exception as e:
                # Catch urllib3 ProtocolError, RemoteDisconnected, etc.
                if "disconnected" in str(e).lower() or "RemoteDisconnected" in str(
                    type(e).__name__
                ):
                    last_error = LLMConnectionError(f"DeepSeek server disconnected: {e}")
                else:
                    raise LLMError(f"DeepSeek API error: {e}")

            # Retry with backoff
            if attempt < 2:
                wait = 2 * (attempt + 1)
                time.sleep(wait)

        if last_error is None:
            raise LLMError("DeepSeek: retries exhausted without recorded error")
        raise last_error
