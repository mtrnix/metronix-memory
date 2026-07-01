import asyncio
from datetime import datetime
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
    fake_github.return_value.get_user.return_value.login = "octocat"
    with patch("github.Github", fake_github), patch("github.Auth") as fake_auth:
        asyncio.run(
            connector.configure(
                conn, {"token": "t", "base_url": "https://ghe/api/v3"}
            )
        )
        _, kwargs = fake_github.call_args
        assert kwargs["base_url"] == "https://ghe/api/v3"
        fake_auth.Token.assert_called_once_with("t")
        assert asyncio.run(connector.health_check()) is True


def test_health_check_false_when_not_configured():
    connector = GitHubConnector()
    assert asyncio.run(connector.health_check()) is False


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
