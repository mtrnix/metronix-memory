"""Tests for date metadata population in connectors and pipeline."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

from metatron.connectors.confluence import ConfluenceConnector
from metatron.connectors.jira import JiraConnector
from metatron.core.models import Document


class TestConfluenceDateMetadata:
    def test_updated_at_from_version_when(self) -> None:
        connector = ConfluenceConnector()
        page = {
            "id": "123",
            "title": "Test Page",
            "body": {"storage": {"value": "<p>hello</p>"}},
            "version": {"when": "2026-02-09T07:46:41.303Z"},
            "history": {
                "createdBy": {"displayName": "Author"},
                "createdDate": "2026-01-15T10:00:00.000Z",
            },
        }
        doc = connector._page_to_document(page, "ws1", "https://test.atlassian.net/wiki", "SPACE")
        assert doc.updated_at is not None
        assert isinstance(doc.updated_at, datetime)
        assert doc.updated_at.strftime("%Y-%m-%d") == "2026-02-09"

    def test_created_at_still_set(self) -> None:
        connector = ConfluenceConnector()
        page = {
            "id": "456",
            "title": "Test",
            "body": {"storage": {"value": "<p>content</p>"}},
            "version": {"when": "2026-02-09T07:46:41.303Z"},
            "history": {
                "createdBy": {"displayName": "A"},
                "createdDate": "2026-01-10T12:00:00.000Z",
            },
        }
        doc = connector._page_to_document(page, "ws1", "https://test.atlassian.net/wiki", "SP")
        assert doc.created_at is not None
        assert doc.created_at.strftime("%Y-%m-%d") == "2026-01-10"

    def test_no_version_when(self) -> None:
        connector = ConfluenceConnector()
        page = {
            "id": "789",
            "title": "Test",
            "body": {"storage": {"value": "<p>content</p>"}},
            "version": {},
            "history": {"createdBy": {"displayName": "A"}},
        }
        doc = connector._page_to_document(page, "ws1", "https://test.atlassian.net/wiki", "SP")
        # updated_at should fallback to default (datetime.utcnow)
        assert doc.updated_at is not None


class TestJiraDateMetadata:
    def _make_raw_issue(
        self,
        created: str = "2026-01-20T08:00:00.000+0000",
        updated: str = "2026-02-10T15:30:00.000+0000",
    ) -> dict:
        return {
            "key": "TEST-1",
            "fields": {
                "summary": "Test issue",
                "status": {"name": "Open"},
                "assignee": {"displayName": "Dev"},
                "reporter": {"displayName": "PM"},
                "created": created,
                "updated": updated,
                "priority": {"name": "Medium"},
                "issuetype": {"name": "Task"},
                "description": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Description"}]}
                    ],
                },
            },
        }

    def test_updated_at_from_structured(self) -> None:
        connector = JiraConnector()
        doc = connector._issue_to_document(self._make_raw_issue(), "ws1")
        assert doc.updated_at is not None
        assert isinstance(doc.updated_at, datetime)
        assert doc.updated_at.strftime("%Y-%m-%d") == "2026-02-10"

    def test_created_at_still_set(self) -> None:
        connector = JiraConnector()
        doc = connector._issue_to_document(self._make_raw_issue(), "ws1")
        assert doc.created_at is not None
        assert doc.created_at.strftime("%Y-%m-%d") == "2026-01-20"

    def test_no_updated_field(self) -> None:
        connector = JiraConnector()
        raw = self._make_raw_issue()
        del raw["fields"]["updated"]
        doc = connector._issue_to_document(raw, "ws1")
        # updated_at should fallback to default
        assert doc.updated_at is not None


class TestPipelineDateExtraction:
    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_date_in_metadata(self, mock_store_fn: AsyncMock) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = AsyncMock()
        mock_store_fn.return_value = mock_store

        doc = Document(
            source_type="confluence",
            source_id="page-1",
            title="Test Page",
            content="Some content here.",
            updated_at=datetime(2026, 2, 9, 7, 46, 41),
            created_at=datetime(2026, 1, 15, 10, 0, 0),
        )
        await ingest_documents([doc], workspace_id="ws1", connector_type="confluence")

        # Verify add_document was called with date in metadata
        assert mock_store.add_document.called
        call_kwargs = mock_store.add_document.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        assert metadata["date"] == "2026-02-09"

    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_date_from_created_at_fallback(self, mock_store_fn: AsyncMock) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = AsyncMock()
        mock_store_fn.return_value = mock_store

        # Document with only created_at (updated_at defaults to utcnow but
        # we explicitly set both to control the test)
        doc = Document(
            source_type="jira",
            source_id="JIRA-1",
            title="Test Issue",
            content="Issue content.",
            created_at=datetime(2026, 1, 20, 8, 0, 0),
        )
        await ingest_documents([doc], workspace_id="ws1", connector_type="jira")

        assert mock_store.add_document.called
        call_kwargs = mock_store.add_document.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        # Should have a date (from updated_at default or created_at)
        assert metadata["date"] != ""

    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_date_prefers_updated_over_created(
        self,
        mock_store_fn: AsyncMock,
    ) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = AsyncMock()
        mock_store_fn.return_value = mock_store

        doc = Document(
            source_type="confluence",
            source_id="page-2",
            title="Test",
            content="Content.",
            updated_at=datetime(2026, 2, 10, 12, 0, 0),
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        await ingest_documents([doc], workspace_id="ws1", connector_type="confluence")

        call_kwargs = mock_store.add_document.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        assert metadata["date"] == "2026-02-10"
