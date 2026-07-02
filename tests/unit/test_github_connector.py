import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metronix.connectors.github import (
    GitHubConnector,
    _collect_until_since,
    _explicit_repo_names,
)
from metronix.connectors.schemas import get_schema
from metronix.core.models import Connection


def test_github_schema_has_base_url_optional():
    schema = get_schema("github")
    assert schema is not None
    field_names = [f.name for f in schema.fields]
    assert "base_url" in field_names
    base_url = next(f for f in schema.fields if f.name == "base_url")
    assert base_url.required is False
    assert base_url.type == "url"


def test_github_schema_token_required_secret():
    schema = get_schema("github")
    token = next(f for f in schema.fields if f.name == "token")
    assert token.required is True
    assert token.type == "secret"
    assert "token" in schema.secret_fields


def test_source_role_is_knowledge_base():
    assert GitHubConnector.source_role == "knowledge_base"


def test_explicit_repo_names_variants():
    assert _explicit_repo_names("acme", "web,api") == ["acme/web", "acme/api"]
    assert _explicit_repo_names("", "acme/web, acme/api") == ["acme/web", "acme/api"]
    assert _explicit_repo_names("acme", "*") is None
    assert _explicit_repo_names("acme", "") is None
    assert _explicit_repo_names("", "") is None


def test_collect_until_since_stops_at_boundary():
    since = datetime.fromisoformat("2026-02-01T00:00:00+00:00")
    items = [
        SimpleNamespace(updated_at=datetime.fromisoformat("2026-02-05T00:00:00+00:00")),
        SimpleNamespace(updated_at=datetime.fromisoformat("2026-02-02T00:00:00+00:00")),
        SimpleNamespace(updated_at=datetime.fromisoformat("2026-01-20T00:00:00+00:00")),
    ]
    kept = _collect_until_since(items, since)
    assert len(kept) == 2
    assert _collect_until_since(items, None) == items


def test_configure_passes_base_url_and_health_check():
    connector = GitHubConnector()
    conn = Connection(id="c1", workspace_id="ws1", connector_type="github")
    fake_github = MagicMock()
    # health_check now probes get_rate_limit() (works for any valid token,
    # unlike get_user() which needs user scope). The MagicMock returns a value
    # without raising, so the probe succeeds.
    with patch("github.Github", fake_github), patch("github.Auth") as fake_auth:
        asyncio.run(connector.configure(conn, {"token": "t", "base_url": "https://ghe/api/v3"}))
        _, kwargs = fake_github.call_args
        assert kwargs["base_url"] == "https://ghe/api/v3"
        fake_auth.Token.assert_called_once_with("t")
        assert asyncio.run(connector.health_check()) is True
        fake_github.return_value.get_rate_limit.assert_called()


def test_health_check_false_when_not_configured():
    connector = GitHubConnector()
    assert asyncio.run(connector.health_check()) is False


def test_health_check_false_when_rate_limit_raises():
    connector = GitHubConnector()
    connector._client = MagicMock()
    connector._client.get_rate_limit.side_effect = Exception("bad token")
    assert asyncio.run(connector.health_check()) is False


def test_resolve_repos_skips_unresolvable_repo():
    """One bad repo name must not abort resolution of the valid ones (#1)."""
    connector = GitHubConnector()
    connector._client = MagicMock()
    connector._config = {"org": "acme", "repos": "good,bad"}

    def _get_repo(name):
        if name == "acme/bad":
            raise Exception("404 Not Found")
        return SimpleNamespace(full_name=name)

    connector._client.get_repo.side_effect = _get_repo
    repos = connector._resolve_repos()
    assert [r.full_name for r in repos] == ["acme/good"]


def test_resolve_repos_skips_bare_name_without_org():
    """A bare repo name with no org (no owner/repo) is skipped, not queried (#1)."""
    connector = GitHubConnector()
    connector._client = MagicMock()
    connector._config = {"org": "", "repos": "web"}
    repos = connector._resolve_repos()
    assert repos == []
    connector._client.get_repo.assert_not_called()


def _fake_content(path, text="# doc"):
    return SimpleNamespace(
        path=path,
        decoded_content=text.encode(),
        html_url=f"https://gh/acme/web/blob/main/{path}",
    )


def test_fetch_files_dedups_non_root_readme_and_warns_on_truncation():
    """Rendered README (any path) is not re-indexed from the tree (#2), and a
    truncated tree emits a warning (#3)."""
    connector = GitHubConnector()
    repo = MagicMock()
    repo.default_branch = "main"
    repo.get_readme.return_value = _fake_content("docs/README.md", "# Readme")
    repo.get_git_tree.return_value = SimpleNamespace(
        truncated=True,
        tree=[
            SimpleNamespace(type="blob", path="docs/README.md", size=100),  # == readme → skip
            SimpleNamespace(type="blob", path="docs/guide.md", size=100),
            SimpleNamespace(type="blob", path="src/app.py", size=100),  # non-md → skip
        ],
    )
    repo.get_contents.side_effect = _fake_content

    with patch("metronix.connectors.github.logger") as log:
        docs = connector._fetch_files(repo, "acme", "web", "ws1")
        warned = [c.args[0] for c in log.warning.call_args_list if c.args]
        assert "github.tree.truncated" in warned

    readme_docs = [d for d in docs if d.source_id.startswith("gh-readme-")]
    doc_docs = [d for d in docs if d.source_id.startswith("gh-doc-")]
    assert len(readme_docs) == 1
    assert sorted(d.metadata["path"] for d in doc_docs) == ["docs/guide.md"]


def _fake_issue(number, is_pr=False):
    label = SimpleNamespace(name="bug")
    obj = SimpleNamespace(
        number=number,
        title=f"Issue {number}",
        state="open",
        body="body",
        html_url=f"https://gh/acme/web/issues/{number}",
        user=SimpleNamespace(login="alice"),
        labels=[label],
        assignees=[SimpleNamespace(login="bob")],
        created_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        updated_at=datetime.fromisoformat("2026-03-01T00:00:00+00:00"),
        closed_at=None,
        pull_request=SimpleNamespace() if is_pr else None,
    )
    obj.get_comments = lambda: []
    return obj


def test_fetch_raises_when_not_configured():
    connector = GitHubConnector()
    with pytest.raises(RuntimeError):
        asyncio.run(connector.fetch("ws1"))


def test_fetch_returns_issue_documents():
    connector = GitHubConnector()
    repo = MagicMock()
    repo.full_name = "acme/web"
    repo.owner = SimpleNamespace(login="acme")
    repo.name = "web"
    repo.get_issues.return_value = [_fake_issue(1), _fake_issue(2, is_pr=True)]
    repo.get_pulls.return_value = []
    repo.get_releases.return_value = []
    repo.get_readme.side_effect = Exception("no readme")
    repo.get_git_tree.side_effect = Exception("no tree")

    connector._client = MagicMock()
    connector._config = {"org": "acme", "repos": "web"}
    connector._client.get_repo.return_value = repo

    docs = asyncio.run(connector.fetch("ws1"))
    issue_docs = [d for d in docs if d.metadata.get("type") == "github_issue"]
    # PR-typed issue (#2) is excluded from issues
    assert len(issue_docs) == 1
    assert issue_docs[0].source_id == "gh-issue-acme-web-1"


def test_release_dict_uses_name_not_title():
    """Regression: _release_dict must use rel.name (not the deprecated rel.title)."""

    fake_release = SimpleNamespace(
        tag_name="v1.2.3",
        name="Release 1.2.3",
        body="Changelog here.",
        author=SimpleNamespace(login="carol"),
        html_url="https://github.com/acme/web/releases/tag/v1.2.3",
        created_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
        published_at=datetime(2026, 1, 15, 13, 0, 0, tzinfo=UTC),
    )
    result = GitHubConnector()._release_dict(fake_release)
    assert result["name"] == "Release 1.2.3"
