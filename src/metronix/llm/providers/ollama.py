"""Ollama LLM provider implementation.

Ollama runs models locally, useful for privacy and offline operation.
"""

import contextlib
import os

import requests
import structlog

from metronix.core.http import get_http_session
from metronix.llm.base import (
    LLMConnectionError,
    LLMError,
    LLMProvider,
    LLMResponse,
    Message,
)

logger = structlog.get_logger()


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize Ollama provider.

        Args:
            model: Model name (e.g., "llama3", "mistral", "codellama").
            host: Ollama server URL (falls back to OLLAMA_LLM_HOST env var).
        """
        super().__init__(model, **kwargs)

        # Build host URL from env vars (compatible with existing config)
        default_host = os.getenv("OLLAMA_LLM_HOST")
        if not default_host:
            # Fall back to OLLAMA_HOST (used for embeddings) if LLM-specific not set
            ollama_host = os.getenv("OLLAMA_HOST", "localhost")
            # OLLAMA_HOST may already be a full URL (e.g. http://ollama:11434)
            if ollama_host.startswith(("http://", "https://")):
                default_host = ollama_host
            else:
                ollama_port = os.getenv("OLLAMA_LLM_PORT", os.getenv("OLLAMA_PORT", "11434"))
                default_host = f"http://{ollama_host}:{ollama_port}"

        self.host = host or default_host
        # Ensure host has http prefix
        if not self.host.startswith(("http://", "https://")):
            self.host = f"http://{self.host}"

    @property
    def default_model(self) -> str:
        return os.getenv("OLLAMA_LLM_MODEL", "llama3")

    @property
    def api_url(self) -> str:
        return f"{self.host}/api/chat"

    def is_available(self) -> bool:
        """Check if Ollama server is running and model is available."""
        try:
            session = get_http_session()
            resp = session.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False

            # Check if our model is in the list
            models = resp.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] for m in models]
            return self.model.split(":")[0] in model_names
        except Exception:
            return False

    def chat_completion(  # TODO: async migration
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
        timeout: int = 120,  # Ollama can be slow for first request
        **kwargs,
    ) -> LLMResponse:
        """Send chat completion request to Ollama."""
        # num_ctx default in Ollama is 2048, which is too small for RAG —
        # Metronix builds prompts of 4k–8k tokens and modern Qwen/Llama
        # models support 128k+, so we default to 32k here. Override via
        # OLLAMA_NUM_CTX if your hardware can't hold the KV cache.
        num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
        # Allow env override of the request timeout for slow local models.
        env_timeout = os.getenv("OLLAMA_REQUEST_TIMEOUT")
        if env_timeout:
            with contextlib.suppress(ValueError):
                timeout = int(env_timeout)
        payload = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }

        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        if json_mode:
            payload["format"] = "json"

        try:
            session = get_http_session()
            resp = session.post(
                self.api_url,
                json=payload,
                timeout=timeout,
            )

            resp.raise_for_status()
            data = resp.json()

            content = data.get("message", {}).get("content", "")

            # Ollama doesn't always return usage info
            eval_count = data.get("eval_count", 0)
            prompt_eval_count = data.get("prompt_eval_count", 0)

            return LLMResponse(
                content=content.strip(),
                model=self.model,
                provider=self.name,
                usage={
                    "prompt_tokens": prompt_eval_count,
                    "completion_tokens": eval_count,
                    "total_tokens": prompt_eval_count + eval_count,
                },
                raw_response=data,
            )

        except requests.exceptions.Timeout:
            raise LLMConnectionError(
                f"Ollama timeout after {timeout}s - is the model loaded?"
            ) from None  # noqa: E501
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to Ollama at {self.host}: {e}") from e
        except requests.exceptions.HTTPError as e:
            raise LLMError(f"Ollama error: {e}") from e
