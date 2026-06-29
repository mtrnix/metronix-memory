"""Tests for ``retrieval.search.fast_search`` + ``_extract_fast_signals`` (PROJ-303)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from metronix.retrieval import search as search_module
from metronix.retrieval.channels import ScoredResult
from metronix.retrieval.search import _extract_fast_signals, fast_search


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
        keys, dates = _extract_fast_signals("status of PROJ-123 and mtrnix-123 today")
        assert keys == ["PROJ-123", "MTRNIX-123"]

        # Multiple distinct keys preserved in order.
        keys, _ = _extract_fast_signals("compare PROJ-1 with PROJ-2")
        assert keys == ["PROJ-1", "PROJ-2"]


class TestFastSearch:
    async def test_fast_search_calls_only_dense_channel(self) -> None:
        dense_hits = [_scored("a", 0.9), _scored("b", 0.5)]

        with (
            patch(
                "metronix.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=dense_hits,
            ) as mock_dense,
            patch(
                "metronix.retrieval.search.recall_metadata_async",
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
                "metronix.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=[_scored("a", 0.1)],
            ),
            patch(
                "metronix.retrieval.search.recall_metadata_async",
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
                "metronix.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=dense_hits,
            ),
            patch(
                "metronix.retrieval.search.recall_metadata_async",
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
                "metronix.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "metronix.retrieval.search.recall_metadata_async",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            out = await fast_search("whatever")
        assert out == []

    async def test_fast_search_runs_metadata_when_flag_on_and_signals_present(self) -> None:
        """Flag ON + Jira key in query → metadata channel is invoked."""
        dense_hits = [_scored("a", 0.5)]
        meta_hits = [_scored("b", 0.9, channel="metadata")]

        with (
            patch.object(search_module._s, "search_fast_include_metadata", True),
            patch(
                "metronix.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=dense_hits,
            ),
            patch(
                "metronix.retrieval.search.recall_metadata_async",
                new_callable=AsyncMock,
                return_value=meta_hits,
            ) as mock_meta,
        ):
            out = await fast_search("status of PROJ-123")

        mock_meta.assert_awaited_once()
        assert {h["id"] for h in out} == {"a", "b"}

    async def test_fast_search_skips_metadata_when_flag_off(self) -> None:
        """Flag OFF + Jira key in query → metadata channel is NOT invoked."""
        dense_hits = [_scored("a", 0.5)]

        with (
            patch.object(search_module._s, "search_fast_include_metadata", False),
            patch(
                "metronix.retrieval.search.recall_dense_async",
                new_callable=AsyncMock,
                return_value=dense_hits,
            ),
            patch(
                "metronix.retrieval.search.recall_metadata_async",
                new_callable=AsyncMock,
                return_value=[_scored("b", 0.9, channel="metadata")],
            ) as mock_meta,
        ):
            out = await fast_search("status of PROJ-123")

        mock_meta.assert_not_called()
        assert [h["id"] for h in out] == ["a"]
