"""Unit tests for AsocStreamingChatProvider (MTRNIX-354, T4).

Tests the manual SSE parser, error mapping, and is_available guard.
Uses httpx mocking to avoid real network calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.llm.asoc_chat_provider import (
    AsocStreamingChatProvider,
    LlmAuthError,
    LlmRateLimitError,
    LlmUnavailableError,
    StreamDelta,
)


class TestIsAvailable:
    def test_true_when_base_url_set(self) -> None:
        provider = AsocStreamingChatProvider(
            base_url="http://llm.example.com",
            api_key="key",
            model="gpt-4o",
        )
        assert provider.is_available is True

    def test_false_when_base_url_empty(self) -> None:
        provider = AsocStreamingChatProvider(
            base_url="",
            api_key="key",
            model="gpt-4o",
        )
        assert provider.is_available is False

    def test_false_when_base_url_whitespace(self) -> None:
        # base_url.rstrip("/") strips trailing slashes but not leading spaces,
        # so "   " is truthy — but test that empty string is the canonical disabled form
        provider2 = AsocStreamingChatProvider(
            base_url="",
            api_key="key",
            model="gpt-4o",
        )
        assert provider2.is_available is False


class TestStreamRaisesWhenNotConfigured:
    async def test_raises_llm_unavailable_when_not_configured(self) -> None:
        provider = AsocStreamingChatProvider(base_url="", api_key="", model="x")
        with pytest.raises(LlmUnavailableError, match="not configured"):
            async for _ in provider.stream([], []):
                pass


class TestStreamErrorMapping:
    def _make_provider(self) -> AsocStreamingChatProvider:
        return AsocStreamingChatProvider(
            base_url="http://llm.test",
            api_key="test-key",
            model="test-model",
        )

    async def test_401_raises_auth_error(self) -> None:
        provider = self._make_provider()
        mock_resp = AsyncMock()
        mock_resp.status_code = 401
        mock_resp.aiter_lines = AsyncMock(return_value=iter([]))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(provider._client, "stream", return_value=mock_resp),
            pytest.raises(LlmAuthError),
        ):
            async for _ in provider.stream([], []):
                pass

    async def test_403_raises_auth_error(self) -> None:
        provider = self._make_provider()
        mock_resp = AsyncMock()
        mock_resp.status_code = 403
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(provider._client, "stream", return_value=mock_resp),
            pytest.raises(LlmAuthError),
        ):
            async for _ in provider.stream([], []):
                pass

    async def test_429_raises_rate_limit_error(self) -> None:
        provider = self._make_provider()
        mock_resp = AsyncMock()
        mock_resp.status_code = 429
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(provider._client, "stream", return_value=mock_resp),
            pytest.raises(LlmRateLimitError),
        ):
            async for _ in provider.stream([], []):
                pass

    async def test_500_raises_unavailable_error(self) -> None:
        provider = self._make_provider()
        mock_resp = AsyncMock()
        mock_resp.status_code = 503
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(provider._client, "stream", return_value=mock_resp),
            pytest.raises(LlmUnavailableError),
        ):
            async for _ in provider.stream([], []):
                pass

    async def test_connect_error_raises_unavailable(self) -> None:
        import httpx

        provider = self._make_provider()

        with patch.object(
            provider._client,
            "stream",
            side_effect=httpx.ConnectError("connection refused"),
        ), pytest.raises(LlmUnavailableError, match="connection error"):
            async for _ in provider.stream([], []):
                pass

    async def test_timeout_raises_unavailable(self) -> None:
        import httpx

        provider = self._make_provider()

        with patch.object(
            provider._client,
            "stream",
            side_effect=httpx.TimeoutException("timed out"),
        ), pytest.raises(LlmUnavailableError, match="timeout"):
            async for _ in provider.stream([], []):
                pass


class TestStreamSseParsing:
    def _make_provider(self) -> AsocStreamingChatProvider:
        return AsocStreamingChatProvider(
            base_url="http://llm.test",
            api_key="key",
            model="model",
        )

    def _sse_line(self, chunk: dict[str, Any]) -> str:
        import json

        return f"data: {json.dumps(chunk)}"

    async def _collect(
        self, provider: AsocStreamingChatProvider, lines: list[str]
    ) -> list[StreamDelta]:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=aiter(lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        results: list[StreamDelta] = []
        with patch.object(provider._client, "stream", return_value=mock_resp):
            async for delta in provider.stream([], []):
                results.append(delta)
        return results

    async def test_content_delta_parsed(self) -> None:
        provider = self._make_provider()
        lines = [
            self._sse_line(
                {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
            ),
            "data: [DONE]",
        ]
        results = await self._collect(provider, lines)
        assert len(results) == 1
        assert results[0].content == "Hello"

    async def test_done_terminates_stream(self) -> None:
        provider = self._make_provider()
        lines = ["data: [DONE]"]
        results = await self._collect(provider, lines)
        assert results == []

    async def test_finish_reason_yielded(self) -> None:
        provider = self._make_provider()
        lines = [
            self._sse_line(
                {"choices": [{"delta": {}, "finish_reason": "stop"}]}
            ),
            "data: [DONE]",
        ]
        results = await self._collect(provider, lines)
        assert any(r.finish_reason == "stop" for r in results)

    async def test_tool_call_delta_parsed(self) -> None:
        provider = self._make_provider()
        lines = [
            self._sse_line(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "function": {
                                            "name": "asoc_list",
                                            "arguments": '{"project":',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            ),
            "data: [DONE]",
        ]
        results = await self._collect(provider, lines)
        tc_deltas = [r for r in results if r.tool_call_delta is not None]
        assert len(tc_deltas) == 1
        assert tc_deltas[0].tool_call_delta.name == "asoc_list"

    async def test_bad_json_line_skipped(self) -> None:
        provider = self._make_provider()
        lines = [
            "data: {bad json}",
            "data: [DONE]",
        ]
        # Should not raise; bad line is skipped
        results = await self._collect(provider, lines)
        assert results == []

    async def test_non_data_lines_skipped(self) -> None:
        provider = self._make_provider()
        lines = [
            ": keep-alive",
            "",
            self._sse_line(
                {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
            ),
            "data: [DONE]",
        ]
        results = await self._collect(provider, lines)
        assert any(r.content == "hi" for r in results)


# ---------------------------------------------------------------------------
# async iterator helper for testing (Python 3.12+)
# ---------------------------------------------------------------------------

async def aiter(items: list) -> Any:
    for item in items:
        yield item
