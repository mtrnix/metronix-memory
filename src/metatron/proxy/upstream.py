"""UpstreamLLMClient — httpx streaming forward to an OAI-compatible upstream."""

from __future__ import annotations

from collections.abc import AsyncIterator  # noqa: TC003
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from metatron.proxy.config import UpstreamConfig

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ProxyStreamFrame:
    """One SSE frame forwarded from upstream. ``raw`` is the exact bytes."""

    raw: bytes


class UpstreamLLMClient:
    """App-level httpx client that streams an enriched request to the upstream LLM."""

    def __init__(
        self,
        *,
        timeout: float,
        max_connections: int = 100,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        limits = httpx.Limits(max_connections=max_connections)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits, transport=transport)
        self.last_status: int | None = None

    async def stream(
        self,
        *,
        upstream: UpstreamConfig,
        api_key: str,
        messages: list[dict[str, Any]],
        request_body: dict[str, Any],
        correlation_id: str,
    ) -> AsyncIterator[ProxyStreamFrame]:
        """Yield raw SSE frames from upstream. Sets last_status. Forwards errors verbatim."""
        url = f"{upstream.resolved_base_url()}/chat/completions"
        outbound: dict[str, Any] = {
            **upstream.params,
            **request_body,
            "messages": messages,
            "model": request_body.get("model") or upstream.model_name,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        async with self._client.stream(
            "POST", url, json=outbound, headers=headers
        ) as response:
            self.last_status = response.status_code
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield ProxyStreamFrame(raw=chunk)

    async def aclose(self) -> None:
        await self._client.aclose()
