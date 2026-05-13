"""Jira connector — fetches issues via REST API.

Uses atlassian-python-api (v4+) with enhanced_jql for Jira Cloud.
Fetches issue summary, description, comments, and changelog.
"""

# TODO: async migration
from __future__ import annotations

import time
from datetime import datetime

import structlog

from metatron.connectors._filter import is_strictly_after
from metatron.connectors.jira_processing import (
    jira_issue_to_markdown,
    process_jira_issue,
)
from metatron.core.interfaces import ConnectorInterface
from metatron.core.models import Connection, Document

logger = structlog.get_logger()


class JiraConnector(ConnectorInterface):
    """Fetches Jira issues for a given project.

    Config keys (decrypted_config):
    - url: Jira base URL (e.g., https://org.atlassian.net)
    - username: API user email
    - api_token: Atlassian API token
    - project_key: Jira project to index (optional — syncs all if empty)
    """

    source_role: str = "task_tracker"

    def __init__(self) -> None:
        self._client = None  # type: ignore[assignment]
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        from atlassian import Jira

        logger.info("jira.configure", connector_id=connection.id)
        self._config = decrypted_config
        self._client = Jira(
            url=decrypted_config["url"],
            username=decrypted_config["username"],
            password=decrypted_config["api_token"],
            cloud=True,
        )

    async def fetch(
        self,
        workspace_id: str,
        since: datetime | None = None,
    ) -> list[Document]:
        logger.info("jira.fetch.started", workspace_id=workspace_id, since=since)
        if self._client is None:
            raise RuntimeError("Connector not configured — call configure() first")

        project_key = self._config.get("project_key", "")
        documents: list[Document] = []

        # JQL's date filter only supports minute precision ("yyyy-MM-dd HH:mm"),
        # so a cursor at 22:09:40 formatted as "22:09" still matches docs from
        # 22:09:00-22:09:59. We use the minute filter as a coarse server-side
        # narrowing and then do a precise post-filter below (MTRNIX-332).
        jql = f'project="{project_key}"' if project_key else "ORDER BY updated DESC"
        if since:
            since_str = since.strftime("%Y-%m-%d %H:%M")
            jql += f' AND updated >= "{since_str}"'
        if "ORDER BY" not in jql:
            jql += " ORDER BY updated DESC"

        limit = 50
        next_token: str | None = None

        while True:
            try:
                kwargs: dict = {"limit": limit, "expand": "changelog"}
                if next_token:
                    kwargs["nextPageToken"] = next_token
                results = self._client.enhanced_jql(jql, **kwargs)
            except Exception as e:
                if "429" in str(e) or "Too Many" in str(e):
                    logger.warning("jira.rate_limit")
                    time.sleep(4)
                    continue
                raise

            issues = results.get("issues", [])
            if not issues:
                break

            for raw_issue in issues:
                # Precise post-filter (MTRNIX-332). JQL only narrows to the
                # minute; here we drop anything whose actual ``updated`` is
                # <= the cursor at sub-minute resolution. We do this BEFORE
                # the (expensive) ``_issue_to_document`` parse — ADF extract
                # + changelog walk + comments parsing is the bulk of the
                # work, no point doing it just to throw the doc away.
                if since is not None and not is_strictly_after(
                    (raw_issue.get("fields") or {}).get("updated"), since
                ):
                    continue
                try:
                    doc = self._issue_to_document(raw_issue, workspace_id)
                    documents.append(doc)
                except Exception as e:
                    logger.warning("jira.issue.error", error=str(e))

            is_last = results.get("isLast", True)
            next_token = results.get("nextPageToken")
            if is_last or not next_token:
                break

            if len(documents) % 100 < limit:
                logger.info("jira.fetch.progress", issues=len(documents))

        logger.info("jira.fetch.done", issues=len(documents))
        return documents

    # NOTE: sub-minute cursor filtering for the JQL minute-precision trap
    # lives in ``metatron.connectors._filter.is_strictly_after`` and is
    # applied directly in ``fetch()`` above — no per-connector parser.

    def _issue_to_document(self, raw_issue: dict, workspace_id: str) -> Document:
        structured = process_jira_issue(raw_issue)
        markdown = jira_issue_to_markdown(structured)
        issue_key = structured.get("key", "UNKNOWN")

        created_str = structured.get("created")
        created_at = None
        if created_str:
            try:
                created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        updated_str = structured.get("updated")
        updated_at = None
        if updated_str:
            try:
                updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        base = self._config.get("url", "").rstrip("/")

        return Document(
            source_type="jira",
            source_id=issue_key,
            url=f"{base}/browse/{issue_key}" if base else "",
            workspace_id=workspace_id,
            title=f"[{issue_key}] {structured.get('summary', '')}",
            content=markdown,
            author=structured.get("reporter") or "",
            metadata={
                "issue_key": issue_key,
                "status": structured.get("status", ""),
                "assignee": structured.get("assignee") or "",
                "assignee_email": structured.get("assignee_email") or "",
                "reporter": structured.get("reporter") or "",
                "reporter_email": structured.get("reporter_email") or "",
                "issuetype": structured.get("issuetype") or "",
                "priority": structured.get("priority") or "",
                "type": "jira",
                "created_at_str": structured.get("created") or "",
                "updated_at_str": structured.get("updated") or "",
                "resolved_at_str": structured.get("resolutiondate") or "",
            },
            **({"created_at": created_at} if created_at else {}),
            **({"updated_at": updated_at} if updated_at else {}),
        )

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.get_all_projects(included_archived=None)
            return True
        except Exception:
            return False
