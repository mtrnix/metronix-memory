"""Tests for parallel graph extraction in the ingestion pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from metronix.core.models import Document
from metronix.ingestion.pipeline import _extract_graphs_parallel


def _make_doc(
    source_id: str = "DOC-1",
    source_type: str = "jira",
    content: str = "A" * 200,
    title: str = "Test Issue",
) -> Document:
    return Document(
        source_type=source_type,
        source_id=source_id,
        title=title,
        content=content,
    )


# ---------------------------------------------------------------------------
# _extract_graphs_parallel
# ---------------------------------------------------------------------------


class TestParallelExtraction:
    @patch("metronix.ingestion.pipeline._write_doc_to_graph")
    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    def test_calls_graph_writer_for_each_document(
        self,
        mock_jira: MagicMock,
        mock_doc: MagicMock,
    ) -> None:
        """3 documents → 3 graph writer calls."""
        queue = [
            (_make_doc("J-1", source_type="jira"), "WS1"),
            (_make_doc("J-2", source_type="jira"), "WS1"),
            (_make_doc("C-1", source_type="confluence"), "WS1"),
        ]
        result = _extract_graphs_parallel(queue, max_workers=2, min_chars=50)

        assert mock_jira.call_count == 2
        assert mock_doc.call_count == 1
        assert result["ok"] == 3
        assert result["errors"] == 0
        assert result["skipped"] == 0

    @patch("metronix.ingestion.pipeline._write_doc_to_graph")
    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    def test_short_non_jira_documents_skipped(
        self,
        mock_jira: MagicMock,
        mock_doc: MagicMock,
    ) -> None:
        """Non-Jira documents with content shorter than min_chars are skipped."""
        queue = [
            (_make_doc("C-1", source_type="confluence", content="short"), "WS1"),
            (_make_doc("J-2", content="A" * 200), "WS1"),
        ]
        result = _extract_graphs_parallel(queue, max_workers=2, min_chars=100)

        assert mock_jira.call_count == 1
        assert result["ok"] == 1
        assert result["skipped"] == 1

    @patch("metronix.ingestion.pipeline._write_doc_to_graph")
    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    def test_error_in_one_does_not_stop_others(
        self,
        mock_jira: MagicMock,
        mock_doc: MagicMock,
    ) -> None:
        """One failing document doesn't prevent the rest from succeeding."""
        # First pass: J-1 fails, J-2 succeeds. Retry: J-1 fails again.
        mock_jira.side_effect = [RuntimeError("LLM timeout"), None, RuntimeError("still down")]
        queue = [
            (_make_doc("J-1", source_type="jira"), "WS1"),
            (_make_doc("J-2", source_type="jira"), "WS1"),
        ]
        result = _extract_graphs_parallel(queue, max_workers=2, min_chars=50)

        # 2 initial calls + 1 retry = 3
        assert mock_jira.call_count == 3
        assert result["ok"] == 1
        assert result["errors"] == 1
        assert "J-1" in result["failed_source_ids"]

    @patch("metronix.ingestion.pipeline._extract_graphs_parallel")
    @patch("metronix.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_disabled_skips_all_graph_extraction(
        self,
        mock_get_store: AsyncMock,
        mock_parallel: MagicMock,
    ) -> None:
        """graph_extraction_enabled=False means no parallel extraction."""
        from metronix.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        mock_get_store.return_value = store

        doc = _make_doc("J-1", content="Some real content for testing graph extraction")

        with patch("metronix.core.config.Settings") as MockSettings:  # noqa: N806
            mock_settings = MockSettings.return_value
            mock_settings.graph_extraction_enabled = False
            mock_settings.graph_extraction_workers = 4
            mock_settings.graph_extraction_min_chars = 100

            await ingest_documents([doc], "WS1", "jira")

        mock_parallel.assert_not_called()

    @patch("metronix.ingestion.pipeline._write_doc_to_graph")
    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    def test_result_counters(
        self,
        mock_jira: MagicMock,
        mock_doc: MagicMock,
    ) -> None:
        """Result dict tracks ok, errors, and skipped correctly."""
        mock_jira.side_effect = [None, ValueError("bad data")]
        queue = [
            (_make_doc("J-1", source_type="jira", content="A" * 200), "WS1"),
            (_make_doc("J-2", source_type="jira", content="A" * 200), "WS1"),
            (_make_doc("C-3", source_type="confluence", content="tiny"), "WS1"),
        ]
        result = _extract_graphs_parallel(queue, max_workers=2, min_chars=100)

        assert result["ok"] == 1
        assert result["errors"] == 1
        assert result["skipped"] == 1
        assert "J-2" in result["failed_source_ids"]

    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    def test_max_workers_passed_to_pool(self, mock_jira: MagicMock) -> None:
        """max_workers parameter is forwarded to ThreadPoolExecutor."""
        queue = [(_make_doc("J-1"), "WS1")]

        with patch(
            "metronix.ingestion.pipeline.ThreadPoolExecutor",
            wraps=__import__(
                "concurrent.futures", fromlist=["ThreadPoolExecutor"]
            ).ThreadPoolExecutor,
        ) as mock_pool_cls:
            _extract_graphs_parallel(queue, max_workers=7, min_chars=50)
            mock_pool_cls.assert_called_once_with(max_workers=7)

    @patch("metronix.ingestion.pipeline._write_doc_to_graph")
    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    def test_short_jira_still_creates_node(
        self,
        mock_jira: MagicMock,
        mock_doc: MagicMock,
    ) -> None:
        """Short Jira docs still get JiraIssue node (skip_llm_extraction=True)."""
        queue = [
            (_make_doc("J-1", source_type="jira", content="short"), "WS1"),
            (_make_doc("C-1", source_type="confluence", content="short"), "WS1"),
        ]
        result = _extract_graphs_parallel(queue, max_workers=2, min_chars=100)

        # Jira short doc: still called with skip_llm_extraction=True
        assert mock_jira.call_count == 1
        call_kwargs = mock_jira.call_args
        assert call_kwargs.kwargs.get("skip_llm_extraction") is True or (
            len(call_kwargs.args) >= 3 and call_kwargs.args[2] is True
        )
        # Confluence short doc: skipped entirely
        assert mock_doc.call_count == 0
        assert result["ok"] == 1
        assert result["skipped"] == 1

    @patch("metronix.ingestion.pipeline._write_doc_to_graph")
    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    def test_short_jira_error_counted(
        self,
        mock_jira: MagicMock,
        mock_doc: MagicMock,
    ) -> None:
        """Error in short Jira struct-only write is counted."""
        mock_jira.side_effect = RuntimeError("Memgraph down")
        queue = [
            (_make_doc("J-1", source_type="jira", content="short"), "WS1"),
        ]
        result = _extract_graphs_parallel(queue, max_workers=2, min_chars=100)

        assert result["errors"] == 1
        assert result["ok"] == 0
