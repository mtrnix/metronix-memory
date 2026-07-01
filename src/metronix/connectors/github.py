"""GitHub connector — fetches README, docs, issues, PRs, and releases.

Uses PyGithub for API access. Pure formatting lives in github_processing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from metronix.core.interfaces import ConnectorInterface
from metronix.core.models import Connection, Document

logger = structlog.get_logger()


def _explicit_repo_names(org: str, repos_csv: str) -> list[str] | None:
    """Resolve an explicit list of ``owner/repo`` names, or None to list via API.

    Returns None when ``repos_csv`` is empty or ``*`` (the caller lists repos
    from the org or the authenticated user). Otherwise splits the CSV and
    qualifies bare names with ``org/`` when an org is set.
    """
    repos_csv = (repos_csv or "").strip()
    if not repos_csv or repos_csv == "*":
        return None
    names: list[str] = []
    for raw in repos_csv.split(","):
        name = raw.strip()
        if not name:
            continue
        if "/" in name:
            names.append(name)
        elif org:
            names.append(f"{org}/{name}")
        else:
            names.append(name)
    return names or None


def _collect_until_since(items, since: datetime | None) -> list:
    """Keep items (newest-updated first) until the first older than ``since``.

    With ``since=None`` keeps everything. Items are expected to have an
    ``updated_at`` datetime attribute.
    """
    if since is None:
        return list(items)
    kept: list = []
    for item in items:
        updated = getattr(item, "updated_at", None)
        if updated is not None and updated < since:
            break
        kept.append(item)
    return kept


class GitHubConnector(ConnectorInterface):
    """Fetches GitHub repository content for indexing.

    Config keys (decrypted_config):
    - token: GitHub personal access token
    - org: organization / owner (optional)
    - repos: "repo1,repo2" or "*" for all in org (optional)
    - base_url: Enterprise Server API base (optional)
    """

    source_role: str = "knowledge_base"

    def __init__(self) -> None:
        self._client = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        from github import Auth, Github

        logger.info("github.configure", connector_id=connection.id)
        self._config = decrypted_config
        kwargs: dict = {"auth": Auth.Token(decrypted_config["token"]), "retry": 3}
        base_url = decrypted_config.get("base_url")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = Github(**kwargs)

    async def fetch(self, workspace_id: str, since: datetime | None = None) -> list[Document]:
        raise NotImplementedError  # implemented in Task 6

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            await asyncio.to_thread(lambda: self._client.get_user().login)
            return True
        except Exception:
            return False
