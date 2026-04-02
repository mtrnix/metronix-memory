"""Notion connector — fetches pages and databases via Notion API.

Uses the official notion-client Python SDK (AsyncClient).
Supports incremental sync via last_edited_time filter.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from metatron.connectors.notion_processing import (
    blocks_to_markdown,
    fetch_all_blocks,
    get_page_title,
)
from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

logger = structlog.get_logger()

_RATE_LIMIT_DELAY = 4


class NotionConnector(ConnectorInterface):
    """Fetches Notion pages and database entries.

    Config keys (decrypted_config):
    - api_token: Notion integration token
    """

    def __init__(self) -> None:
        self._client = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Initialize the Notion API client."""
        from notion_client import AsyncClient

        logger.info("notion.configure", connector_id=connection.id)
        self._config = decrypted_config
        self._client = AsyncClient(auth=decrypted_config["api_token"])

    async def fetch(
        self,
        workspace_id: str,
        since: datetime | None = None,
    ) -> list[Document]:
        """Fetch Notion pages using search API with pagination."""
        logger.info("notion.fetch.started", workspace_id=workspace_id, since=since)
        if self._client is None:
            raise RuntimeError("Connector not configured — call configure() first")

        pages = await self._search_pages(since)
        documents: list[Document] = []

        for page in pages:
            try:
                doc = await self._page_to_document(page, workspace_id)
                documents.append(doc)
            except Exception as exc:
                logger.warning("notion.page.error", page_id=page.get("id"), error=str(exc))

            if len(documents) % 50 == 0 and documents:
                logger.info("notion.fetch.progress", pages=len(documents))

        logger.info("notion.fetch.done", pages=len(documents))
        return documents

    async def _search_pages(self, since: datetime | None = None) -> list[dict]:
        """Search all pages via Notion API with pagination.

        Args:
            since: If set, only return pages edited after this time.

        Returns:
            List of page objects from the Notion API.
        """
        all_pages: list[dict] = []
        cursor = None
        search_filter = {"property": "object", "value": "page"}

        while True:
            kwargs: dict = {"filter": search_filter, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            if since:
                kwargs["sort"] = {
                    "direction": "descending",
                    "timestamp": "last_edited_time",
                }

            try:
                resp = await self._client.search(**kwargs)
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    logger.warning("notion.rate_limit", pages_so_far=len(all_pages))
                    await asyncio.sleep(_RATE_LIMIT_DELAY)
                    continue
                raise

            pages = resp.get("results", [])

            for page in pages:
                edited_str = page.get("last_edited_time", "")
                if since and edited_str:
                    edited = datetime.fromisoformat(edited_str.replace("Z", "+00:00"))
                    since_aware = since.replace(tzinfo=UTC) if since.tzinfo is None else since
                    if edited < since_aware:
                        return all_pages
                all_pages.append(page)

            if len(all_pages) % 100 == 0 and all_pages:
                logger.info("notion.search.progress", pages=len(all_pages))

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        return all_pages

    async def _page_to_document(self, page: dict, workspace_id: str) -> Document:
        """Convert a Notion page to a Document."""
        page_id = page["id"]
        title = get_page_title(page) or "(untitled)"
        url = page.get("url", "")

        blocks = await fetch_all_blocks(self._client, page_id)
        content = await blocks_to_markdown(self._client, blocks, title=title)

        created_str = page.get("created_time", "")
        edited_str = page.get("last_edited_time", "")

        created_at = None
        if created_str:
            try:
                created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        updated_at = None
        if edited_str:
            try:
                updated_at = datetime.fromisoformat(edited_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        created_by = page.get("created_by", {})
        author = created_by.get("name", "") or created_by.get("id", "")
        last_edited_by = page.get("last_edited_by", {})
        last_edited_by_name = last_edited_by.get("name", "") or last_edited_by.get("id", "")

        return Document(
            source_type="notion",
            source_id=page_id,
            workspace_id=workspace_id,
            title=title,
            content=content,
            url=url,
            author=author,
            metadata={
                "page_id": page_id,
                "type": "notion",
                "last_edited_time": edited_str,
                "created_by": author,
                "last_edited_by": last_edited_by_name,
            },
            **({"created_at": created_at} if created_at else {}),
            **({"updated_at": updated_at} if updated_at else {}),
        )

    async def health_check(self) -> bool:
        """Test Notion API connectivity via users.me()."""
        if self._client is None:
            return False
        try:
            await self._client.users.me()
            return True
        except Exception:
            return False
