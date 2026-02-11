"""Notion connector — fetches pages and databases via Notion API.

Uses the official notion-client Python SDK.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

logger = structlog.get_logger()


class NotionConnector(ConnectorInterface):
    """Fetches Notion pages and database entries.

    Config keys (decrypted_config):
    - api_token: Notion integration token
    - root_page_id: (optional) Only index pages under this parent
    """

    def __init__(self) -> None:
        self._client = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Initialize the Notion API client."""
        logger.info("notion.configure", connector_id=connection.id)
        self._config = decrypted_config
        # TODO: implement client initialization
        # from notion_client import AsyncClient
        # self._client = AsyncClient(auth=decrypted_config["api_token"])

    async def fetch(
        self, workspace_id: str, since: datetime | None = None
    ) -> list[Document]:
        """Fetch Notion pages using search API with pagination.

        Notion blocks are recursive — we need to recursively fetch
        child blocks to build full page content.

        Args:
            workspace_id: Target workspace.
            since: If set, filter by last_edited_time.
        """
        logger.info("notion.fetch.started", workspace_id=workspace_id, since=since)
        # TODO: implement Notion page iteration
        # 1. Use self._client.search() with pagination (start_cursor)
        # 2. Filter by page type and last_edited_time
        # 3. For each page: fetch child blocks recursively
        # 4. Convert blocks to plain text
        # 5. Build Document with title, content, URL, tags
        raise NotImplementedError("Notion fetch not yet implemented")

    async def health_check(self) -> bool:
        """Test Notion API connectivity."""
        logger.info("notion.health_check")
        return False
