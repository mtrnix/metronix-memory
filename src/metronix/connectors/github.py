"""GitHub connector — fetches README, docs, issues, PRs, and releases.

Uses PyGithub for API access. Pure formatting lives in github_processing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from metronix.connectors.github_processing import (
    issue_to_document,
    pr_to_document,
    release_to_document,
    repo_file_to_document,
)
from metronix.core.interfaces import ConnectorInterface
from metronix.core.models import Connection, Document

logger = structlog.get_logger()

_MAX_FILE_BYTES = 1_000_000


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

    # Retrieval impact (intentional): one role applies to ALL emitted docs.
    # "knowledge_base" makes GitHub content PRIMARY evidence for `documentation`
    # queries; issues/PRs are still fully retrievable but are SUPPORTING (not
    # PRIMARY) for `execution`/`temporal` queries, which map to `task_tracker`
    # in retrieval.search.PROFILE_PRIMARY_ROLE. Chosen because docs/README/
    # releases dominate GitHub knowledge value; see test_source_role_* .
    source_role: str = "knowledge_base"

    def __init__(self) -> None:
        self._client = None
        self._config: dict[str, str] = {}

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        from github import Auth, Github

        logger.info("github.configure", connector_id=connection.id)
        self._config = decrypted_config
        # No explicit ``retry``: PyGithub's default is GithubRetry(total=10) with a
        # rate-limit-aware status_forcelist. Passing a bare int would resolve via
        # urllib3.Retry.from_int with an EMPTY status_forcelist (zero 403/429/5xx
        # retries) — weaker than the default.
        kwargs: dict = {"auth": Auth.Token(decrypted_config["token"])}
        base_url = decrypted_config.get("base_url")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = Github(**kwargs)

    async def fetch(self, workspace_id: str, since: datetime | None = None) -> list[Document]:
        logger.info("github.fetch.started", workspace_id=workspace_id, since=since)
        if self._client is None:
            raise RuntimeError("Connector not configured — call configure() first")

        repos = await asyncio.to_thread(self._resolve_repos)
        documents: list[Document] = []
        for repo in repos:
            try:
                repo_docs = await asyncio.to_thread(self._fetch_repo, repo, workspace_id, since)
                documents.extend(repo_docs)
            except Exception as exc:
                logger.warning(
                    "github.repo.error",
                    repo=getattr(repo, "full_name", "?"),
                    error=str(exc),
                )
        logger.info("github.fetch.done", documents=len(documents))
        return documents

    def _resolve_repos(self) -> list:
        org = self._config.get("org", "")
        names = _explicit_repo_names(org, self._config.get("repos", ""))
        if names is not None:
            # Validate the token/connectivity ONCE up front. A revoked/expired
            # token (or an unreachable host) raises here and aborts the whole
            # sync loudly — it is never masked as a successful empty sync. With
            # that guaranteed, per-repo failures below can be skipped broadly:
            # a single missing/typo'd/transiently-failing repo must not abort
            # resolution of the rest (per-repo data-fetch resilience also lives
            # in fetch()/_fetch_repo).
            self._client.get_rate_limit()
            repos: list = []
            for n in names:
                if "/" not in n:
                    logger.warning(
                        "github.repo.skip_invalid",
                        name=n,
                        reason="expected 'owner/repo' — set an Organization or use a full name",
                    )
                    continue
                try:
                    repos.append(self._client.get_repo(n))
                except Exception as exc:
                    logger.warning("github.repo.skip", name=n, error=str(exc))
            return repos
        if org:
            return list(self._client.get_organization(org).get_repos())
        return list(self._client.get_user().get_repos())

    def _fetch_repo(self, repo, workspace_id: str, since: datetime | None) -> list[Document]:
        owner = repo.owner.login
        name = repo.name
        docs: list[Document] = []
        docs.extend(self._fetch_files(repo, owner, name, workspace_id))
        docs.extend(self._fetch_issues(repo, owner, name, workspace_id, since))
        docs.extend(self._fetch_prs(repo, owner, name, workspace_id, since))
        docs.extend(self._fetch_releases(repo, owner, name, workspace_id))
        return docs

    def _fetch_files(self, repo, owner, name, workspace_id) -> list[Document]:
        docs: list[Document] = []
        readme_path: str | None = None
        try:
            readme = repo.get_readme()
            readme_path = readme.path
            docs.append(
                repo_file_to_document(
                    readme.path,
                    readme.decoded_content.decode("utf-8", errors="replace"),
                    readme.html_url,
                    owner,
                    name,
                    workspace_id,
                    is_readme=True,
                )
            )
        except Exception as exc:
            logger.debug("github.readme.skip", repo=f"{owner}/{name}", error=str(exc))
        try:
            tree = repo.get_git_tree(repo.default_branch, recursive=True)
            if getattr(tree, "truncated", False):
                logger.warning("github.tree.truncated", repo=f"{owner}/{name}")
            for entry in tree.tree:
                if entry.type != "blob" or not entry.path.endswith(".md"):
                    continue
                # Skip the file already emitted as the rendered README (any
                # path — root, docs/, .github/), else it gets a duplicate
                # gh-doc-* document with identical content.
                if readme_path is not None and entry.path == readme_path:
                    continue
                if (entry.size or 0) > _MAX_FILE_BYTES:
                    continue
                try:
                    cf = repo.get_contents(entry.path)
                    text = cf.decoded_content.decode("utf-8", errors="replace")
                    docs.append(
                        repo_file_to_document(
                            entry.path,
                            text,
                            cf.html_url,
                            owner,
                            name,
                            workspace_id,
                            is_readme=False,
                        )
                    )
                except Exception as exc:
                    logger.warning("github.file.error", path=entry.path, error=str(exc))
        except Exception as exc:
            logger.debug("github.tree.skip", repo=f"{owner}/{name}", error=str(exc))
        return docs

    def _fetch_issues(self, repo, owner, name, workspace_id, since) -> list[Document]:
        since_kwarg = {"since": since} if since else {}
        docs: list[Document] = []
        for issue in repo.get_issues(state="all", sort="updated", direction="desc", **since_kwarg):
            # The issues list payload carries ``pull_request`` only for PRs.
            # Read it from the already-fetched raw list data — accessing the
            # ``issue.pull_request`` property would trigger a per-item lazy
            # completion GET (doubling API calls on issue-heavy repos).
            if (getattr(issue, "_rawData", None) or {}).get("pull_request"):
                continue
            try:
                docs.append(issue_to_document(self._issue_dict(issue), owner, name, workspace_id))
            except Exception as exc:
                logger.warning("github.issue.error", error=str(exc))
        return docs

    def _fetch_prs(self, repo, owner, name, workspace_id, since) -> list[Document]:
        pulls = _collect_until_since(
            repo.get_pulls(state="all", sort="updated", direction="desc"), since
        )
        docs: list[Document] = []
        for pr in pulls:
            try:
                docs.append(pr_to_document(self._pr_dict(pr), owner, name, workspace_id))
            except Exception as exc:
                logger.warning("github.pr.error", error=str(exc))
        return docs

    def _fetch_releases(self, repo, owner, name, workspace_id) -> list[Document]:
        docs: list[Document] = []
        for rel in repo.get_releases():
            try:
                docs.append(
                    release_to_document(self._release_dict(rel), owner, name, workspace_id)
                )
            except Exception as exc:
                logger.warning("github.release.error", error=str(exc))
        return docs

    @staticmethod
    def _dt_str(value) -> str:
        return value.isoformat() if value else ""

    @staticmethod
    def _comment_dicts(comments) -> list[dict]:
        return [
            {
                "author": getattr(c.user, "login", "") if c.user else "",
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "body": c.body or "",
            }
            for c in comments
        ]

    def _issue_dict(self, issue) -> dict:
        return {
            "number": issue.number,
            "title": issue.title or "",
            "state": issue.state or "",
            "body": issue.body or "",
            "html_url": issue.html_url or "",
            "user": getattr(issue.user, "login", "") if issue.user else "",
            "labels": [lbl.name for lbl in issue.labels],
            "assignees": [a.login for a in issue.assignees],
            "created_at": self._dt_str(issue.created_at),
            "updated_at": self._dt_str(issue.updated_at),
            "closed_at": self._dt_str(issue.closed_at),
            "comments": self._comment_dicts(issue.get_comments()),
        }

    def _pr_dict(self, pr) -> dict:
        review_comments = [
            {
                "author": getattr(c.user, "login", "") if c.user else "",
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "body": c.body or "",
                "path": getattr(c, "path", "") or "",
            }
            for c in pr.get_review_comments()
        ]
        return {
            "number": pr.number,
            "title": pr.title or "",
            "state": pr.state or "",
            "body": pr.body or "",
            "html_url": pr.html_url or "",
            "user": getattr(pr.user, "login", "") if pr.user else "",
            "labels": [lbl.name for lbl in pr.labels],
            "assignees": [a.login for a in pr.assignees],
            # Use merged_at (present in the pulls list payload) rather than
            # `pr.merged` (absent from the list → a lazy completion GET per PR).
            "merged": bool(getattr(pr, "merged_at", None)),
            "base": getattr(pr.base, "ref", "") if pr.base else "",
            "head": getattr(pr.head, "ref", "") if pr.head else "",
            "created_at": self._dt_str(pr.created_at),
            "updated_at": self._dt_str(pr.updated_at),
            "closed_at": self._dt_str(pr.closed_at),
            "comments": self._comment_dicts(pr.get_issue_comments()),
            "review_comments": review_comments,
        }

    def _release_dict(self, rel) -> dict:
        return {
            "tag": rel.tag_name or "",
            "name": rel.name or "",
            "body": rel.body or "",
            "author": getattr(rel.author, "login", "") if rel.author else "",
            "html_url": rel.html_url or "",
            "created_at": self._dt_str(rel.created_at),
            "published_at": self._dt_str(rel.published_at),
        }

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            # get_rate_limit() succeeds for any valid token (classic/fine-grained
            # PAT), unlike get_user() which needs user scope and can yield a
            # false negative for repo-scoped tokens.
            await asyncio.to_thread(self._client.get_rate_limit)
            return True
        except Exception:
            return False
