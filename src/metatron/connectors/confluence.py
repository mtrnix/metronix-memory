"""Confluence connector — fetches pages via REST API.

Uses atlassian-python-api for CQL queries and page body retrieval.
Supports incremental sync via lastModified CQL filter.
"""
# TODO: async migration
from __future__ import annotations

import time
from datetime import datetime

import structlog

from metatron.connectors.confluence_processing import process_confluence_page
from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

logger = structlog.get_logger()


class ConfluenceConnector(ConnectorInterface):
    """Fetches Confluence wiki pages for a given space.

    Config keys (decrypted_config):
    - url: Confluence base URL (e.g., https://org.atlassian.net/wiki)
    - username: API user email
    - api_token: Atlassian API token
    - space_key: Confluence space to index (optional — syncs all if empty)
    """

    def __init__(self) -> None:
        self._client = None  # type: ignore[assignment]
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        from atlassian import Confluence

        logger.info("confluence.configure", connector_id=connection.id)
        self._config = decrypted_config
        self._client = Confluence(
            url=decrypted_config["url"],
            username=decrypted_config["username"],
            password=decrypted_config["api_token"],
        )

    async def fetch(
        self, workspace_id: str, since: datetime | None = None,
    ) -> list[Document]:
        logger.info("confluence.fetch.started", workspace_id=workspace_id, since=since)
        if self._client is None:
            raise RuntimeError("Connector not configured — call configure() first")

        space_key = self._config.get("space_key", "")
        base_url = self._config["url"].rstrip("/")

        if since:
            return self._fetch_incremental(workspace_id, base_url, space_key, since)
        return self._fetch_full(workspace_id, base_url, space_key)

    def _fetch_full(
        self, workspace_id: str, base_url: str, space_key: str,
    ) -> list[Document]:
        """Full sync using content API (returns body.storage)."""
        documents: list[Document] = []
        start, limit = 0, 25
        expand = "body.storage,version,history"

        while True:
            try:
                if space_key:
                    pages = self._client.get_all_pages_from_space(
                        space_key, start=start, limit=limit, expand=expand,
                    )
                else:
                    pages = self._client.get_all_pages_from_space(
                        None, start=start, limit=limit, expand=expand,
                    )
            except Exception as e:
                if "429" in str(e) or "Too Many" in str(e):
                    logger.warning("confluence.rate_limit", start=start)
                    time.sleep(4)
                    continue
                raise

            if not pages:
                break

            for page in pages:
                try:
                    doc = self._page_to_document(page, workspace_id, base_url, space_key)
                    documents.append(doc)
                except Exception as e:
                    logger.warning("confluence.page.error", error=str(e))

            if len(pages) < limit:
                break
            start += limit
            if len(documents) % 50 < limit:
                logger.info("confluence.fetch.progress", pages=len(documents))

        logger.info("confluence.fetch.done", pages=len(documents))
        return documents

    def _fetch_incremental(
        self, workspace_id: str, base_url: str, space_key: str, since: datetime,
    ) -> list[Document]:
        """Incremental sync using CQL (lastModified filter), then fetch each page."""
        documents: list[Document] = []
        cql = f'space="{space_key}" AND type=page' if space_key else "type=page"
        cql += f' AND lastModified > "{since.strftime("%Y-%m-%d %H:%M")}"'

        start, limit = 0, 25
        while True:
            try:
                results = self._client.cql(cql, start=start, limit=limit)
            except Exception as e:
                if "429" in str(e) or "Too Many" in str(e):
                    logger.warning("confluence.rate_limit", start=start)
                    time.sleep(4)
                    continue
                raise

            page_results = results.get("results", [])
            if not page_results:
                break

            for item in page_results:
                content_ref = item.get("content", {})
                page_id = content_ref.get("id")
                if not page_id:
                    continue
                try:
                    page = self._client.get_page_by_id(
                        page_id, expand="body.storage,version,history",
                    )
                    doc = self._page_to_document(page, workspace_id, base_url, space_key)
                    documents.append(doc)
                except Exception as e:
                    logger.warning("confluence.page.error", page_id=page_id, error=str(e))

            start += limit
            total = results.get("totalSize", results.get("size", 0))
            if start >= total:
                break

        logger.info("confluence.fetch.done", pages=len(documents))
        return documents

    def _page_to_document(self, page: dict, workspace_id: str,
                          base_url: str, space_key: str) -> Document:
        page_id = str(page.get("id", ""))
        html_body = page.get("body", {}).get("storage", {}).get("value", "")
        api_title = page.get("title", "")

        title, content = process_confluence_page(html_body, page_title=api_title)

        version = page.get("version", {})
        history = page.get("history", {})
        author = history.get("createdBy", {}).get("displayName", "")
        last_modified = version.get("when", "")
        labels = [lb["name"] for lb in page.get("metadata", {}).get("labels", {}).get("results", [])]

        created_str = history.get("createdDate")
        created_at = datetime.fromisoformat(created_str) if created_str else None

        updated_at = None
        if last_modified:
            try:
                updated_at = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return Document(
            source_type="confluence",
            source_id=page_id,
            workspace_id=workspace_id,
            title=title,
            content=content,
            url=f"{base_url}/spaces/{space_key}/pages/{page_id}",
            author=author,
            tags=labels,
            metadata={
                "space_key": space_key,
                "page_id": page_id,
                "last_modified": last_modified,
                "type": "confluence",
            },
            **({"created_at": created_at} if created_at else {}),
            **({"updated_at": updated_at} if updated_at else {}),
        )

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.get_all_spaces(limit=1)
            return True
        except Exception:
            return False
