"""Entry point for the Telegram bot.

Usage:
    python -m metatron.channels.run_telegram

Reads TELEGRAM_BOT_TOKEN from environment / .env file.
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from metatron.agent.router import AgentRouter
from metatron.channels.telegram import TelegramChannel
from metatron.core.config import Settings

logger = structlog.get_logger()


def main() -> None:
    """Start the Telegram bot with long-polling."""
    settings = Settings()

    if not settings.telegram_bot_token:
        logger.error("telegram.no_token", hint="Set TELEGRAM_BOT_TOKEN in .env")
        sys.exit(1)

    router = AgentRouter(settings=settings)
    channel = TelegramChannel(
        bot_token=settings.telegram_bot_token,
        router=router,
        settings=settings,
    )

    logger.info(
        "telegram.starting",
        workspace=settings.default_workspace_id,
        llm_provider=settings.llm_provider,
    )

    asyncio.run(channel.start())


if __name__ == "__main__":
    main()
