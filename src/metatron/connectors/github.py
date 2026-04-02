"""GitHub connector — fetches README, issues, PRs, and wiki pages.

Uses PyGithub for API access. Indexes repository documentation,
open/closed issues, and pull request discussions.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

logger = structlog.get_logger()


class GitHubConnector(ConnectorInterface):
    """Fetches GitHub repository content for indexing.

    Config keys (decrypted_config):
    - token: GitHub personal access token or app token
    - org: GitHub organization name
    - repos: Comma-separated repo names (or "*" for all)
    """

    source_role: str = "task_tracker"

    def __init__(self) -> None:
        self._client = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Initialize the GitHub API client."""
        logger.info("github.configure", connector_id=connection.id)
        self._config = decrypted_config
        # TODO: implement client initialization
        # from github import Github
        # self._client = Github(decrypted_config["token"])

    async def fetch(self, workspace_id: str, since: datetime | None = None) -> list[Document]:
        """Fetch GitHub content: READMEs, issues, PRs.

        For each repo:
        1. Fetch README.md → Document (source_type=github, tags=[repo_name])
        2. Fetch issues (since filter on updated_at)
        3. Fetch PRs with review comments

        Args:
            workspace_id: Target workspace.
            since: If set, only fetch items updated after this time.
        """
        logger.info("github.fetch.started", workspace_id=workspace_id, since=since)
        # TODO: implement GitHub content fetching
        # 1. Parse repos from config (or list all if "*")
        # 2. For each repo: fetch README, issues, PRs
        # 3. Build Documents with appropriate metadata
        # 4. Handle rate limits (X-RateLimit headers)
        raise NotImplementedError("GitHub fetch not yet implemented")

    async def health_check(self) -> bool:
        """Test GitHub API connectivity."""
        logger.info("github.health_check")
        return False
