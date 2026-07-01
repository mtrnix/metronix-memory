from metronix.connectors.schemas import get_schema


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


import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from metronix.connectors.github import (
    GitHubConnector,
    _collect_until_since,
    _explicit_repo_names,
)
from metronix.core.models import Connection


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
