"""Channel manager — dynamic start/stop of messaging channels from DB config.

Queries PostgreSQL for enabled channel connections, starts the appropriate
bot (Telegram, Discord, Slack) with decrypted credentials, and manages
graceful shutdown. Used by app.py's run_all() to replace env-var-based
channel startup.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog

from metatron.agent.router import AgentRouter
from metatron.storage.postgres import PostgresStore

logger = structlog.get_logger()

# Mapping from connector_type to the channel class import path.
# Lazy-imported to avoid pulling in heavy deps (aiogram, discord.py, etc.)
# when no channels are configured.
_CHANNEL_TYPES = frozenset({"telegram", "discord", "slack"})


def _sanitize_error(error: str) -> str:
    """Remove sensitive info from error messages before logging."""
    error = re.sub(r"://[^:]+:[^@]+@", "://***:***@", error)
    error = re.sub(r"/Users/[^\s]+", "/...", error)
    error = re.sub(r"/home/[^\s]+", "/...", error)
    error = re.sub(
        r"(token|key|secret|password)[\s=:]+\S+",
        r"\1=***",
        error,
        flags=re.IGNORECASE,
    )
    if len(error) > 500:
        error = error[:500] + "..."
    return error


class ChannelManager:
    """Manages dynamic start/stop of messaging channels based on DB config."""

    def __init__(
        self,
        router: AgentRouter,
        store: PostgresStore,
        mapper: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._router = router
        self._store = store
        self._mapper = mapper
        self._event_bus = event_bus
        self._running: dict[str, Any] = {}  # connection_id → channel instance
        self._tasks: dict[str, asyncio.Task] = {}  # connection_id → task

    async def start_channels_from_db(
        self,
        fernet_key: str,
        default_workspace_id: str,
    ) -> int:
        """Query DB for enabled channel connections and start each one.

        Returns the number of channels started.
        """
        if not fernet_key:
            logger.warning("channel_manager.no_fernet_key")
            return 0

        from metatron.connectors.schemas import CONNECTOR_SCHEMAS

        connections = await self._store.list_connections(
            default_workspace_id, fernet_key,
        )

        started = 0
        for conn in connections:
            ctype = conn["connector_type"]
            schema = CONNECTOR_SCHEMAS.get(ctype)
            if not schema or schema.category != "channel":
                continue
            if not conn.get("enabled", True):
                logger.info(
                    "channel_manager.skip_disabled",
                    connection_id=conn["id"],
                    connector_type=ctype,
                )
                continue

            # Need decrypted config for tokens
            decrypted = await self._store.get_connection_decrypted(
                conn["id"], fernet_key,
            )

            if not decrypted:
                logger.warning(
                    "channel_manager.decrypt_failed",
                    connection_id=conn["id"],
                )
                continue

            workspace_id = conn.get("workspace_id", default_workspace_id)

            try:
                await self.start_channel(
                    conn["id"], ctype, decrypted["config"],
                    workspace_id=workspace_id,
                )
                started += 1
            except Exception as exc:
                logger.error(
                    "channel_manager.start_failed",
                    connection_id=conn["id"],
                    connector_type=ctype,
                    error=_sanitize_error(str(exc)),
                    exc_info=True,
                )

        logger.info("channel_manager.started", channels=started)
        return started

    async def start_channel(
        self,
        connection_id: str,
        connector_type: str,
        config: dict,
        workspace_id: str | None = None,
    ) -> None:
        """Start a single channel with the given decrypted config."""
        if connection_id in self._running:
            logger.warning(
                "channel_manager.already_running",
                connection_id=connection_id,
            )
            return

        channel = _create_channel(
            connector_type, config, self._router,
            workspace_id=workspace_id,
            mapper=self._mapper,
            event_bus=self._event_bus,
        )
        self._running[connection_id] = channel

        task = asyncio.create_task(
            _run_channel_safe(connection_id, connector_type, channel),
        )
        self._tasks[connection_id] = task
        logger.info(
            "channel_manager.channel_started",
            connection_id=connection_id,
            connector_type=connector_type,
        )

    async def stop_channel(self, connection_id: str) -> None:
        """Gracefully stop a running channel."""
        channel = self._running.pop(connection_id, None)
        task = self._tasks.pop(connection_id, None)

        if channel is None:
            return

        try:
            await channel.stop()
        except Exception as exc:
            logger.warning(
                "channel_manager.stop_error",
                connection_id=connection_id,
                error=_sanitize_error(str(exc)),
            )

        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        logger.info(
            "channel_manager.channel_stopped",
            connection_id=connection_id,
        )

    async def stop_all(self) -> None:
        """Stop all running channels (for shutdown)."""
        ids = list(self._running.keys())
        for cid in ids:
            await self.stop_channel(cid)
        logger.info("channel_manager.all_stopped", count=len(ids))

    async def restart_channel(
        self,
        connection_id: str,
        connector_type: str,
        config: dict,
        workspace_id: str | None = None,
    ) -> None:
        """Stop and restart a channel with new config."""
        await self.stop_channel(connection_id)
        await self.start_channel(
            connection_id, connector_type, config,
            workspace_id=workspace_id,
        )

    @property
    def running_count(self) -> int:
        return len(self._running)

    @property
    def running_ids(self) -> list[str]:
        return list(self._running.keys())


def _create_channel(
    connector_type: str,
    config: dict,
    router: AgentRouter,
    workspace_id: str | None = None,
    mapper: Any | None = None,
    event_bus: Any | None = None,
) -> Any:
    """Create a channel instance from type and config dict."""
    if connector_type == "telegram":
        from metatron.channels.telegram import TelegramChannel

        bot_token = config.get("bot_token", "")
        if not bot_token:
            msg = "Telegram bot_token is required"
            raise ValueError(msg)
        return TelegramChannel(
            bot_token=bot_token, router=router, workspace_id=workspace_id,
            mapper=mapper, event_bus=event_bus,
        )

    if connector_type == "discord":
        from metatron.channels.discord import DiscordChannel

        bot_token = config.get("bot_token", "")
        if not bot_token:
            msg = "Discord bot_token is required"
            raise ValueError(msg)
        return DiscordChannel(
            bot_token=bot_token, router=router, workspace_id=workspace_id,
            mapper=mapper, event_bus=event_bus,
        )

    if connector_type == "slack":
        from metatron.channels.slack import SlackChannel

        bot_token = config.get("bot_token", "")
        app_token = config.get("app_token", "")
        if not bot_token or not app_token:
            msg = "Slack bot_token and app_token are required"
            raise ValueError(msg)
        return SlackChannel(
            bot_token=bot_token, app_token=app_token, router=router,
            workspace_id=workspace_id, mapper=mapper, event_bus=event_bus,
        )

    msg = f"Unknown channel type: {connector_type}"
    raise ValueError(msg)


async def _run_channel_safe(
    connection_id: str, connector_type: str, channel: Any,
) -> None:
    """Run a channel with crash isolation."""
    try:
        await channel.start()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error(
            "channel_manager.channel_crashed",
            connection_id=connection_id,
            connector_type=connector_type,
            error=_sanitize_error(str(exc)),
            exc_info=True,
        )
