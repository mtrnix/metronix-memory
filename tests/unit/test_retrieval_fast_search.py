"""Tests for ``retrieval.search.fast_search`` + ``_extract_fast_signals`` (MTRNIX-303)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from metatron.retrieval.channels import ScoredResult
from metatron.retrieval.search import _extract_fast_signals, fast_search


def _scored(chunk_id: str, score: float, channel: str = "dense") -> ScoredResult:
    return ScoredResult(
        chunk_id=chunk_id,
        doc_label=f"DOC-{chunk_id}",
        score=score,
        memory={
            "id": chunk_id,
            "doc_label": f"DOC-{chunk_id}",
            "title": f"Title-{chunk_id}",
            "memory": f"content-{chunk_id}",
            "score": score,
        },
        channel=channel,
    )


class TestExtractFastSignals:
    def test_extract_fast_signals(self) -> None:
        # Plain query — no signals.
        keys, dates = _extract_fast_signals("who owns the roadmap?")
        assert keys == []
        assert dates is None

        # Jira key — extracted and uppercased, deduplicated.
        keys, dates = _extract_fast_signals("status of MTRNIX-123 and mtrnix-123 today")
        assert keys == ["MTRNIX-123"]

        # Multiple distinct keys preserved in order.
        keys, _ = _extract_fast_signals("compare MTRNIX-1 with MTRNIX-2")
        assert keys == ["MTRNIX-1", "MTRNIX-2"]


class TestFastSearch:
    async def test_fast_search_calls_only_dense_channel(self) -> None:
        dense_hits = [_scored("a", 0.9), _scored("b", 0.5)]

        with (
            patch(
                "metatron.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=dense_hits,
            ) as mock_dense,
            patch(
                "metatron.retrieval.search.recall_metadata_async",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_meta,
        ):
            out = await fast_search("plain query without signals", top_k=5)

        assert mock_dense.await_count == 1
        assert mock_meta.await_count == 0
        assert len(out) == 2
        assert out[0]["id"] == "a"
        assert out[1]["id"] == "b"

    async def test_fast_search_skips_metadata_when_no_signals(self) -> None:
        with (
            patch(
                "metatron.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=[_scored("a", 0.1)],
            ),
            patch(
                "metatron.retrieval.search.recall_metadata_async",
                new_callable=AsyncMock,
                return_value=[_scored("b", 0.9, channel="metadata")],
            ) as mock_meta,
        ):
            out = await fast_search("totally plain")

        # Metadata channel must not have been awaited when no signals present.
        mock_meta.assert_not_called()
        assert [h["id"] for h in out] == ["a"]

    async def test_fast_search_respects_top_k(self) -> None:
        dense_hits = [_scored(str(i), 1.0 - i * 0.05) for i in range(20)]
        with (
            patch(
                "metatron.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=dense_hits,
            ),
            patch(
                "metatron.retrieval.search.recall_metadata_async",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            out = await fast_search("plain", top_k=3)
        assert len(out) == 3
        assert [h["id"] for h in out] == ["0", "1", "2"]

    async def test_fast_search_returns_empty_on_zero_hits(self) -> None:
        with (
            patch(
                "metatron.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "metatron.retrieval.search.recall_metadata_async",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            out = await fast_search("whatever")
        assert out == []
