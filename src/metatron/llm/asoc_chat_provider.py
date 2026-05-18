"""OpenAI-compatible async streaming LLM client for ASOC chat (MTRNIX-354, T4).

``AsocStreamingChatProvider`` wraps an OpenAI-compatible endpoint (e.g. vLLM,
OpenAI, Azure OpenAI, or any chat-completions-compatible API) and streams
responses as typed :class:`StreamDelta` objects.

Tool-call accumulation follows the OpenAI streaming spec:
- Each streaming chunk may carry ``choices[0].delta.tool_calls``.
- Each entry in that list has an ``index`` (stable across the whole response)
  and incremental ``id``, ``function.name``, and ``function.arguments`` fields.
- The caller collects deltas indexed by ``index`` and reassembles them once the
  ``finish_reason`` is ``tool_calls``.

Error mapping:
    LlmAuthError       — HTTP 401 / 403.
    LlmRateLimitError  — HTTP 429.
    LlmUnavailableError — HTTP 5xx / connection / timeout error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)

__all__ = [
    "AsocStreamingChatProvider",
    "LlmAuthError",
    "LlmRateLimitError",
    "LlmUnavailableError",
    "StreamDelta",
    "ToolCallDelta",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LlmAuthError(Exception):
    """HTTP 401 / 403 from the LLM endpoint."""


class LlmRateLimitError(Exception):
    """HTTP 429 from the LLM endpoint."""


class LlmUnavailableError(Exception):
    """HTTP 5xx / network / timeout error from the LLM endpoint."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ToolCallDelta:
    """Single streaming tool-call delta fragment."""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str | None = None


@dataclass
class StreamDelta:
    """One SSE chunk parsed from the LLM streaming response."""

    content: str | None = None
    tool_call_delta: ToolCallDelta | None = None
    finish_reason: str | None = None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class AsocStreamingChatProvider:
    """Async OpenAI-compatible streaming chat client.

    Instantiate once at app startup (in the lifespan) and share across
    requests.  Call :meth:`aclose` during shutdown to release the httpx client.

    Args:
        base_url: Base URL of the OpenAI-compatible API
            (e.g. ``https://api.openai.com``).  Empty string disables the
            provider — :attr:`is_available` returns ``False``.
        api_key: Bearer API key sent in the ``Authorization`` header.
        model: Model name forwarded to the API.
        temperature: Sampling temperature (0 = deterministic).
        max_tokens: Maximum tokens in the completion.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        if self.base_url:
            self._client: httpx.AsyncClient | None = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
            )
        else:
            self._client = None

    @property
    def is_available(self) -> bool:
        """Return ``True`` if the provider is configured and ready."""
        return bool(self.base_url and self._client)

    async def stream(
        self,
        messages: list[dict],  # type: ignore[type-arg]
        tools: list[dict],  # type: ignore[type-arg]
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Stream chat completions from the LLM endpoint.

        Args:
            messages: List of OpenAI-format message dicts
                (``{"role": ..., "content": ...}``).
            tools: List of OpenAI function-call tool schemas.
            model: Override instance-level model name.
            temperature: Override instance-level temperature.
            max_tokens: Override instance-level max_tokens.

        Yields:
            :class:`StreamDelta` objects, one per SSE event.

        Raises:
            LlmAuthError: HTTP 401 / 403.
            LlmRateLimitError: HTTP 429.
            LlmUnavailableError: HTTP 5xx / connection / timeout.
        """
        if not self._client:
            raise LlmUnavailableError("LLM endpoint not configured")

        body: dict = {  # type: ignore[type-arg]
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                content=json.dumps(body),
            ) as resp:
                if resp.status_code in (401, 403):
                    raise LlmAuthError(f"LLM auth error: HTTP {resp.status_code}")
                if resp.status_code == 429:
                    raise LlmRateLimitError("LLM rate limit exceeded")
                if resp.status_code >= 500:
                    raise LlmUnavailableError(f"LLM server error: HTTP {resp.status_code}")
                if resp.status_code != 200:
                    raise LlmUnavailableError(f"LLM unexpected status: {resp.status_code}")

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[len("data: ") :]
                    if data_str.strip() == "[DONE]":
                        return

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("asoc_chat_provider.bad_sse_json", data=data_str[:120])
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})
                    finish_reason: str | None = choice.get("finish_reason")

                    # Text content delta.
                    content_piece: str | None = delta.get("content")
                    if content_piece:
                        yield StreamDelta(content=content_piece)

                    # Tool-call deltas.
                    tc_list = delta.get("tool_calls")
                    if tc_list:
                        for tc_entry in tc_list:
                            index = tc_entry.get("index", 0)
                            tc_id: str | None = tc_entry.get("id")
                            func: dict = tc_entry.get("function", {})  # type: ignore[type-arg]
                            tc_name: str | None = func.get("name")
                            args_delta: str | None = func.get("arguments")
                            yield StreamDelta(
                                tool_call_delta=ToolCallDelta(
                                    index=index,
                                    id=tc_id,
                                    name=tc_name,
                                    arguments_delta=args_delta,
                                )
                            )

                    # Finish reason (may arrive with or without content/tool deltas).
                    if finish_reason:
                        yield StreamDelta(finish_reason=finish_reason)

        except (LlmAuthError, LlmRateLimitError, LlmUnavailableError):
            raise
        except httpx.ConnectError as exc:
            raise LlmUnavailableError(f"LLM connection error: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise LlmUnavailableError(f"LLM timeout: {exc}") from exc
        except httpx.RemoteProtocolError as exc:
            raise LlmUnavailableError(f"LLM protocol error: {exc}") from exc
        except Exception as exc:
            raise LlmUnavailableError(f"LLM unexpected error: {exc}") from exc

    async def aclose(self) -> None:
        """Close the underlying httpx client (call during app shutdown)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
