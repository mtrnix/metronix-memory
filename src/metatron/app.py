"""Unified entry point — runs API server and channel bots in one process.

Starts FastAPI (uvicorn), Telegram bot, and Discord bot as concurrent
async tasks sharing a single AgentRouter instance. Each channel is
started only if its token is configured in the environment.

Usage:
    python -m metatron.app
"""

from __future__ import annotations

import asyncio

import structlog
import uvicorn

from metatron.agent.router import AgentRouter
from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.core.logging import configure_logging

logger = structlog.get_logger()


async def _run_api(settings: Settings) -> None:
    """Run FastAPI via uvicorn as an async server."""
    app = create_app(settings)
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _run_channel_safe(name: str, coro: asyncio.coroutines) -> None:
    """Run a channel coroutine with crash isolation and logging."""
    try:
        await coro
    except Exception as e:
        logger.error("channel.crashed", channel=name, error=str(e), exc_info=True)


async def _run_telegram(router: AgentRouter, settings: Settings) -> None:
    """Run Telegram bot if token is configured."""
    from metatron.channels.telegram import TelegramChannel

    channel = TelegramChannel(
        bot_token=settings.telegram_bot_token,
        router=router,
        settings=settings,
    )
    logger.info("app.telegram.starting")
    await channel.start()


async def _run_discord(router: AgentRouter, settings: Settings) -> None:
    """Run Discord bot if token is configured."""
    from metatron.channels.discord import DiscordChannel

    channel = DiscordChannel(
        bot_token=settings.discord_bot_token,
        router=router,
        settings=settings,
    )
    logger.info("app.discord.starting")
    await channel.start()


async def _run_slack(router: AgentRouter, settings: Settings) -> None:
    """Run Slack bot if tokens are configured."""
    from metatron.channels.slack import SlackChannel

    channel = SlackChannel(
        bot_token=settings.slack_bot_token,
        app_token=settings.slack_app_token,
        router=router,
        settings=settings,
    )
    logger.info("app.slack.starting")
    await channel.start()


async def run_all() -> None:
    """Start all configured services in a single event loop."""
    settings = Settings()
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )

    router = AgentRouter(settings=settings)

    tasks: list[asyncio.Task] = []

    # API server — always runs
    tasks.append(asyncio.create_task(_run_api(settings)))
    logger.info("app.api.scheduled", port=settings.port)

    # Telegram — only if token is set
    if settings.telegram_bot_token:
        tasks.append(asyncio.create_task(
            _run_channel_safe("telegram", _run_telegram(router, settings))
        ))
        logger.info("app.telegram.scheduled")
    else:
        logger.warning("app.telegram.skipped", reason="TELEGRAM_BOT_TOKEN not set")

    # Discord — only if token is set
    if settings.discord_bot_token:
        tasks.append(asyncio.create_task(
            _run_channel_safe("discord", _run_discord(router, settings))
        ))
        logger.info("app.discord.scheduled")
    else:
        logger.warning("app.discord.skipped", reason="DISCORD_BOT_TOKEN not set")

    # Slack — only if both tokens are set
    if settings.slack_bot_token and settings.slack_app_token:
        tasks.append(asyncio.create_task(
            _run_channel_safe("slack", _run_slack(router, settings))
        ))
        logger.info("app.slack.scheduled")
    else:
        logger.warning("app.slack.skipped", reason="SLACK_BOT_TOKEN or SLACK_APP_TOKEN not set")

    logger.info("app.starting", services=len(tasks))
    await asyncio.gather(*tasks)


def main() -> None:
    """CLI entry point for unified launcher."""
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
