"""Tests for file upload — extension validation, parsing, pipeline integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from metatron.agent.router import AgentRouter
from metatron.agent.sessions import SessionManager
from metatron.core.models import SyncResult


@pytest.fixture(autouse=True)
def _reset_sessions():
    SessionManager.reset_instance()
    yield
    SessionManager.reset_instance()


@pytest.fixture
def settings():
    s = MagicMock()
    s.default_workspace_id = "TEST_WS"
    s.confluence_url = ""
    s.jira_url = ""
    s.llm_provider = "deepseek"
    s.llm_fallback_provider = ""
    return s


@pytest.fixture
def router(settings):
    return AgentRouter(settings=settings, sessions=SessionManager())


def _sync_result(**kwargs) -> SyncResult:
    defaults = dict(
        connector_type="upload", workspace_id="TEST_WS",
        documents_fetched=1, documents_new=1, documents_updated=0,
        documents_skipped=0, errors=[], duration_ms=10.0,
    )
    defaults.update(kwargs)
    return SyncResult(**defaults)


class TestExtensionValidation:
    def test_supported_text_extensions_accepted(self, router: AgentRouter) -> None:
        for ext in (".txt", ".md", ".html", ".htm"):
            result = router._parse_upload(b"dummy content here!", f"file{ext}", ext)
            assert isinstance(result, str)

    def test_supported_csv_accepted(self, router: AgentRouter) -> None:
        csv_data = b"col1,col2\na,b"
        result = router._parse_upload(csv_data, "file.csv", ".csv")
        assert isinstance(result, str)
        assert "a" in result

    def test_unsupported_extension_rejected(self, router: AgentRouter) -> None:
        for ext in (".pdf", ".docx", ".jpg", ".zip", ".py"):
            result = router.handle_file_upload(
                b"data", f"file{ext}", user_id="u1",
            )
            assert "Unsupported file type" in result
            assert ext in result

    def test_supported_formats_listed_in_rejection(self, router: AgentRouter) -> None:
        result = router.handle_file_upload(b"data", "photo.jpg", user_id="u1")
        assert ".txt" in result
        assert ".csv" in result
        assert ".html" in result


class TestSizeValidation:
    def test_file_too_large_rejected(self, router: AgentRouter) -> None:
        huge = b"x" * (21 * 1024 * 1024)
        result = router.handle_file_upload(huge, "big.txt", user_id="u1")
        assert "too large" in result.lower()

    def test_file_within_limit_accepted(self, router: AgentRouter) -> None:
        small = b"x" * 100
        with patch("metatron.ingestion.pipeline.ingest_documents", return_value=_sync_result()):
            result = router.handle_file_upload(small, "ok.txt", user_id="u1")
        assert "Indexed" in result


class TestEmptyFile:
    def test_empty_file_rejected(self, router: AgentRouter) -> None:
        result = router.handle_file_upload(b"", "empty.txt", user_id="u1")
        assert "empty" in result.lower()

    def test_whitespace_only_rejected(self, router: AgentRouter) -> None:
        result = router.handle_file_upload(b"   \n\n  ", "blank.txt", user_id="u1")
        assert "empty" in result.lower() or "too short" in result.lower()


class TestFileParsing:
    def test_txt_file_decoded(self, router: AgentRouter) -> None:
        text = router._parse_upload("Hello world!".encode(), "doc.txt", ".txt")
        assert text == "Hello world!"

    def test_md_file_decoded(self, router: AgentRouter) -> None:
        text = router._parse_upload("# Heading\nBody".encode(), "doc.md", ".md")
        assert "Heading" in text

    def test_html_file_processed(self, router: AgentRouter) -> None:
        html = b"<h1>Title</h1><p>Paragraph text</p>"
        text = router._parse_upload(html, "page.html", ".html")
        assert "Title" in text
        assert "Paragraph" in text

    def test_csv_file_processed(self, router: AgentRouter) -> None:
        csv_data = b"name,age\nAlice,30\nBob,25"
        text = router._parse_upload(csv_data, "data.csv", ".csv")
        assert "Alice" in text
        assert "Bob" in text

    def test_utf8_fallback_to_latin1(self, router: AgentRouter) -> None:
        latin1_bytes = "café".encode("latin-1")
        text = router._parse_upload(latin1_bytes, "file.txt", ".txt")
        assert "caf" in text


class TestDocumentMetadata:
    @patch("metatron.ingestion.pipeline.ingest_documents")
    def test_document_has_correct_metadata(
        self, mock_ingest: MagicMock, router: AgentRouter,
    ) -> None:
        mock_ingest.return_value = _sync_result()
        router.handle_file_upload(
            b"Some content for indexing",
            "report.txt",
            user_id="u1",
        )
        mock_ingest.assert_called_once()
        docs = mock_ingest.call_args.args[0]
        assert len(docs) == 1
        doc = docs[0]
        assert doc.source_type == "upload"
        assert doc.title == "Some content for indexing"  # extracted from first line
        assert doc.source_id == "upload:report.txt"
        assert doc.metadata["type"] == "upload"
        assert doc.metadata["filename"] == "report.txt"
        assert doc.author == "u1"

    @patch("metatron.ingestion.pipeline.ingest_documents")
    def test_incremental_mode_enabled(
        self, mock_ingest: MagicMock, router: AgentRouter,
    ) -> None:
        mock_ingest.return_value = _sync_result()
        router.handle_file_upload(b"Content for incremental test", "f.txt", user_id="u1")
        call_kwargs = mock_ingest.call_args
        assert call_kwargs.kwargs.get("incremental") is True or call_kwargs[1].get("incremental") is True


class TestPipelineIntegration:
    @patch("metatron.ingestion.pipeline.ingest_documents")
    def test_successful_upload_reports_new(
        self, mock_ingest: MagicMock, router: AgentRouter,
    ) -> None:
        mock_ingest.return_value = _sync_result(documents_new=1)
        result = router.handle_file_upload(b"Content here!", "doc.txt", user_id="u1")
        assert "Indexed doc.txt" in result
        assert "1 new" in result

    @patch("metatron.ingestion.pipeline.ingest_documents")
    def test_re_upload_reports_updated(
        self, mock_ingest: MagicMock, router: AgentRouter,
    ) -> None:
        mock_ingest.return_value = _sync_result(documents_new=0, documents_updated=1)
        result = router.handle_file_upload(b"Updated content!", "doc.txt", user_id="u1")
        assert "Indexed doc.txt" in result
        assert "1 updated" in result


class TestErrorHandling:
    def test_corrupt_csv_returns_friendly_message(self, router: AgentRouter) -> None:
        result = router.handle_file_upload(
            b"\x00\x01\x02\x03\x04binary garbage",
            "bad.csv",
            user_id="u1",
        )
        assert "Could not parse" in result or "empty" in result.lower()

    @patch("metatron.ingestion.pipeline.ingest_documents")
    def test_pipeline_error_returns_friendly_message(
        self, mock_ingest: MagicMock, router: AgentRouter,
    ) -> None:
        mock_ingest.side_effect = RuntimeError("Qdrant down")
        result = router.handle_file_upload(b"Good content here", "doc.txt", user_id="u1")
        assert "Error processing" in result
        assert "Qdrant" not in result


class TestTitleExtraction:
    def test_markdown_heading(self, router: AgentRouter) -> None:
        assert router._extract_title_from_content(
            "# Deployment Guide\n\nSome body text here.", "file.md",
        ) == "Deployment Guide"

    def test_markdown_h2(self, router: AgentRouter) -> None:
        assert router._extract_title_from_content(
            "## Architecture Overview\n\nDetails.", "file.md",
        ) == "Architecture Overview"

    def test_first_line_fallback(self, router: AgentRouter) -> None:
        assert router._extract_title_from_content(
            "Project Aurora Status Report\n\nThis is the body.", "report.txt",
        ) == "Project Aurora Status Report"

    def test_skips_short_lines(self, router: AgentRouter) -> None:
        assert router._extract_title_from_content(
            "Hi\n\nThis is the actual meaningful title line\nMore content.", "f.txt",
        ) == "This is the actual meaningful title line"

    def test_skips_empty_lines(self, router: AgentRouter) -> None:
        assert router._extract_title_from_content(
            "\n\n\nReal Title of the Document\nBody.", "f.txt",
        ) == "Real Title of the Document"

    def test_falls_back_to_filename(self, router: AgentRouter) -> None:
        assert router._extract_title_from_content("", "notes.txt") == "notes.txt"

    def test_falls_back_when_all_lines_too_short(self, router: AgentRouter) -> None:
        assert router._extract_title_from_content("Hi\nOk\nYes\nNo\nBye", "f.txt") == "f.txt"

    def test_heading_only_hashes_skipped(self, router: AgentRouter) -> None:
        """A line like '###' with no text should be skipped."""
        assert router._extract_title_from_content(
            "###\nActual title of the document\nBody.", "f.md",
        ) == "Actual title of the document"

    @patch("metatron.ingestion.pipeline.ingest_documents")
    def test_extracted_title_used_in_document(
        self, mock_ingest: MagicMock, router: AgentRouter,
    ) -> None:
        mock_ingest.return_value = _sync_result()
        router.handle_file_upload(
            b"# My Important Report\n\nBody text goes here.",
            "report.md", user_id="u1",
        )
        doc = mock_ingest.call_args.args[0][0]
        assert doc.title == "My Important Report"
        assert doc.metadata["filename"] == "report.md"
