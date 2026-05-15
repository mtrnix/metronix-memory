"""``python -m metatron.chat`` — run the chat history cleanup worker."""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.chat.cleanup import ChatHistoryCleanupWorker
from metatron.chat.persistence import ChatPersistence
from metatron.core.config import get_settings
from metatron.core.logging import configure_logging

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )
    logger.info("chat.cleanup.init", retention_days=settings.chat_history_retention_days)
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    persistence = ChatPersistence(engine)
    worker = ChatHistoryCleanupWorker(
        persistence,
        retention_days=settings.chat_history_retention_days,
        interval_seconds=settings.chat_history_cleanup_interval_seconds,
    )
    try:
        await worker.run_forever()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
