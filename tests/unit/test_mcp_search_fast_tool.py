"""Tests for ``metronix_search_fast`` MCP tool (PROJ-303)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestSearchFastTool:
    async def test_search_fast_happy_path(self) -> None:
        hits = [
            {
                "doc_label": "DOC-1",
                "title": "First doc",
                "memory": "contents of first",
                "type": "confluence",
                "score": 0.87,
                "url": "https://example.com/1",
                "date": "2026-04-01",
            },
            {
                "doc_label": "DOC-2",
                "title": "Second doc",
                "data": "contents of second",
                "source_type": "jira",
                "score": 0.55,
                "url": "",
                "date": "",
            },
        ]
        with patch(
            "metronix.retrieval.search.fast_search",
            new_callable=AsyncMock,
            return_value=hits,
        ):
            from metronix.mcp.tools.search_fast import metronix_search_fast

            out = await metronix_search_fast(
                query="anything",
                workspace_id="default",
                top_k=10,
            )

        assert "error" not in out
        assert out["count"] == 2
        assert out["results"][0]["doc_label"] == "DOC-1"
        assert out["results"][0]["source_type"] == "confluence"
        assert out["results"][0]["content"] == "contents of first"
        assert out["results"][1]["content"] == "contents of second"
        assert out["results"][1]["source_type"] == "jira"
        assert isinstance(out["latency_ms"], int)
        assert out["latency_ms"] >= 0

    async def test_search_fast_empty_results(self) -> None:
        with patch(
            "metronix.retrieval.search.fast_search",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from metronix.mcp.tools.search_fast import metronix_search_fast

            out = await metronix_search_fast(query="nothing")

        assert "error" not in out
        assert out["count"] == 0
        assert out["results"] == []

    async def test_search_fast_exception_wrapped(self) -> None:
        with patch(
            "metronix.retrieval.search.fast_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("qdrant timeout"),
        ):
            from metronix.mcp.tools.search_fast import metronix_search_fast

            out = await metronix_search_fast(query="boom")

        assert "error" in out
        assert out["error"]["code"] in {"INTERNAL_ERROR", "QDRANT_UNAVAILABLE"}
