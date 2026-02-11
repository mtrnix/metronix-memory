"""Jira connector — fetches issues via REST API.

Uses atlassian-python-api for JQL queries. Fetches issue summary,
description, comments, and labels.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

logger = structlog.get_logger()


class JiraConnector(ConnectorInterface):
    """Fetches Jira issues for a given project.

    Config keys (decrypted_config):
    - base_url: Jira base URL (e.g., https://org.atlassian.net)
    - email: API user email
    - api_token: Atlassian API token
    - project_key: Jira project to index
    """

    def __init__(self) -> None:
        self._client = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Initialize the Jira API client."""
        logger.info("jira.configure", connector_id=connection.id)
        self._config = decrypted_config
        # TODO: implement client initialization
        # from atlassian import Jira
        # self._client = Jira(url=..., username=..., password=...)

    async def fetch(
        self, workspace_id: str, since: datetime | None = None
    ) -> list[Document]:
        """Fetch Jira issues via JQL pagination.

        For each issue: title = summary, content = description + comments,
        tags = labels + components, metadata = status, assignee, priority.

        Args:
            workspace_id: Target workspace.
            since: If set, uses JQL updated >= "since" for incremental sync.
        """
        logger.info("jira.fetch.started", workspace_id=workspace_id, since=since)
        # TODO: implement Jira issue iteration
        # 1. Build JQL (project = KEY, with since filter if provided)
        # 2. Paginate (startAt, maxResults=50)
        # 3. For each issue: fetch comments, build Document
        # 4. Handle rate limits with exponential backoff
        raise NotImplementedError("Jira fetch not yet implemented")

    async def health_check(self) -> bool:
        """Test Jira API connectivity."""
        logger.info("jira.health_check")
        return False
