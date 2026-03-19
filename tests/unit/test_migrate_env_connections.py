"""Tests for storage/migrate_env_connections.py — env→DB migration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.storage.migrate_env_connections import (
    _collect_configs_from_env,
    _ENV_MAPPINGS,
    migrate_env_to_db,
)


# ---------------------------------------------------------------------------
# _collect_configs_from_env
# ---------------------------------------------------------------------------


class TestCollectConfigsFromEnv:
    def test_empty_env(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _collect_configs_from_env() == {}

    def test_single_connector_full(self) -> None:
        env = {
            "CONFLUENCE_URL": "https://acme.atlassian.net",
            "CONFLUENCE_USERNAME": "bot@acme.com",
            "CONFLUENCE_API_TOKEN": "tok-123",
            "CONFLUENCE_SPACE_KEY": "ENG",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _collect_configs_from_env()
        assert result == {
            "confluence": {
                "url": "https://acme.atlassian.net",
                "username": "bot@acme.com",
                "api_token": "tok-123",
                "space_key": "ENG",
            },
        }

    def test_multiple_connectors(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "tg-token",
            "NOTION_API_TOKEN": "notion-secret",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _collect_configs_from_env()
        assert "telegram" in result
        assert "notion" in result
        assert result["telegram"] == {"bot_token": "tg-token"}
        assert result["notion"] == {"api_token": "notion-secret"}

    def test_blank_values_ignored(self) -> None:
        env = {"CONFLUENCE_URL": "", "CONFLUENCE_USERNAME": "   "}
        with patch.dict("os.environ", env, clear=True):
            assert _collect_configs_from_env() == {}

    def test_partial_connector(self) -> None:
        """Only some env vars set — still collected (validation happens later)."""
        env = {"JIRA_URL": "https://acme.atlassian.net"}
        with patch.dict("os.environ", env, clear=True):
            result = _collect_configs_from_env()
        assert result == {"jira": {"url": "https://acme.atlassian.net"}}


# ---------------------------------------------------------------------------
# migrate_env_to_db
# ---------------------------------------------------------------------------


class TestMigrateEnvToDb:
    """Tests for the async migration function.

    PostgresStore is mocked — we test the orchestration logic, not DB I/O.
    """

    @pytest.fixture()
    def mock_store(self) -> AsyncMock:
        store = AsyncMock()
        store.list_connections = AsyncMock(return_value=[])
        store.create_connection = AsyncMock()
        store.close = AsyncMock()
        return store

    @pytest.fixture(autouse=True)
    def _patch_store(self, mock_store: AsyncMock) -> None:  # type: ignore[misc]
        with patch(
            "metatron.storage.postgres.PostgresStore",
            return_value=mock_store,
        ):
            yield

    async def test_no_env_vars_noop(self, mock_store: AsyncMock) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = await migrate_env_to_db("dsn", "ws-1", "fernet-key")
        assert result == {"created": [], "skipped": [], "errors": []}
        mock_store.create_connection.assert_not_called()

    async def test_no_fernet_key_noop(self) -> None:
        env = {"TELEGRAM_BOT_TOKEN": "tg-tok"}
        with patch.dict("os.environ", env, clear=True):
            result = await migrate_env_to_db("dsn", "ws-1", "")
        assert result == {"created": [], "skipped": [], "errors": []}

    async def test_creates_connections(self, mock_store: AsyncMock) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "tg-tok",
            "NOTION_API_TOKEN": "notion-tok",
        }
        with patch.dict("os.environ", env, clear=True):
            result = await migrate_env_to_db("dsn", "ws-1", "fernet-key")

        assert sorted(result["created"]) == ["notion", "telegram"]
        assert mock_store.create_connection.call_count == 2

    async def test_skips_existing(self, mock_store: AsyncMock) -> None:
        """If connector_type already in DB, skip without creating."""
        mock_store.list_connections.return_value = [
            {"connector_type": "telegram", "id": "existing-1"},
        ]
        env = {"TELEGRAM_BOT_TOKEN": "tg-tok"}
        with patch.dict("os.environ", env, clear=True):
            result = await migrate_env_to_db("dsn", "ws-1", "fernet-key")

        assert result["skipped"] == ["telegram"]
        assert result["created"] == []
        mock_store.create_connection.assert_not_called()

    async def test_idempotent_second_run(self, mock_store: AsyncMock) -> None:
        """Running migration twice should not duplicate connections."""
        env = {"DISCORD_BOT_TOKEN": "dc-tok"}

        # First run — creates
        with patch.dict("os.environ", env, clear=True):
            r1 = await migrate_env_to_db("dsn", "ws-1", "fernet-key")
        assert r1["created"] == ["discord"]

        # Simulate that the connection now exists in DB
        mock_store.list_connections.return_value = [
            {"connector_type": "discord", "id": "created-1"},
        ]
        mock_store.create_connection.reset_mock()

        # Second run — skips
        with patch.dict("os.environ", env, clear=True):
            r2 = await migrate_env_to_db("dsn", "ws-1", "fernet-key")
        assert r2["skipped"] == ["discord"]
        assert r2["created"] == []
        mock_store.create_connection.assert_not_called()

    async def test_incomplete_config_skipped(self, mock_store: AsyncMock) -> None:
        """If required fields are missing, connector is skipped (not errored)."""
        # Confluence requires url, username, api_token — only url provided
        env = {"CONFLUENCE_URL": "https://acme.atlassian.net"}
        with patch.dict("os.environ", env, clear=True):
            result = await migrate_env_to_db("dsn", "ws-1", "fernet-key")

        assert result["skipped"] == ["confluence"]
        assert result["created"] == []
        mock_store.create_connection.assert_not_called()

    async def test_create_failure_captured(self, mock_store: AsyncMock) -> None:
        """If store.create_connection raises, it ends up in 'errors'."""
        mock_store.create_connection.side_effect = RuntimeError("DB down")
        env = {"TELEGRAM_BOT_TOKEN": "tg-tok"}
        with patch.dict("os.environ", env, clear=True):
            result = await migrate_env_to_db("dsn", "ws-1", "fernet-key")

        assert result["errors"] == ["telegram"]
        assert result["created"] == []

    async def test_store_closed_on_success(self, mock_store: AsyncMock) -> None:
        env = {"TELEGRAM_BOT_TOKEN": "tg-tok"}
        with patch.dict("os.environ", env, clear=True):
            await migrate_env_to_db("dsn", "ws-1", "fernet-key")
        mock_store.close.assert_awaited_once()

    async def test_store_closed_on_error(self, mock_store: AsyncMock) -> None:
        mock_store.list_connections.side_effect = RuntimeError("boom")
        env = {"TELEGRAM_BOT_TOKEN": "tg-tok"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError):
                await migrate_env_to_db("dsn", "ws-1", "fernet-key")
        mock_store.close.assert_awaited_once()

    async def test_uses_schema_label_as_name(self, mock_store: AsyncMock) -> None:
        """Connection name should come from ConnectorSchema.label."""
        env = {"TELEGRAM_BOT_TOKEN": "tg-tok"}
        with patch.dict("os.environ", env, clear=True):
            await migrate_env_to_db("dsn", "ws-1", "fernet-key")

        call_kwargs = mock_store.create_connection.call_args.kwargs
        assert call_kwargs["name"] == "Telegram Bot"

    async def test_slack_all_fields(self, mock_store: AsyncMock) -> None:
        """Slack needs bot_token + app_token (signing_secret optional)."""
        env = {
            "SLACK_BOT_TOKEN": "xoxb-123",
            "SLACK_APP_TOKEN": "xapp-456",
            "SLACK_SIGNING_SECRET": "sec-789",
        }
        with patch.dict("os.environ", env, clear=True):
            result = await migrate_env_to_db("dsn", "ws-1", "fernet-key")

        assert result["created"] == ["slack"]
        call_kwargs = mock_store.create_connection.call_args.kwargs
        assert call_kwargs["config"] == {
            "bot_token": "xoxb-123",
            "app_token": "xapp-456",
            "signing_secret": "sec-789",
        }
