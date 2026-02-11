"""Telegram channel adapter — aiogram 3.x bot integration.

Implements ChannelInterface. Uses aiogram 3.x for long-polling
or webhook-based message handling.
"""

from __future__ import annotations

import structlog

from metatron.agent.router import MessageRouter
from metatron.core.interfaces import ChannelInterface
from metatron.core.models import IncomingMessage, OutgoingMessage

logger = structlog.get_logger()


class TelegramChannel(ChannelInterface):
    """Telegram bot adapter using aiogram 3.x.

    Receives messages via long-polling (MVP) or webhooks (production).
    Maps Telegram users to internal users via auth.user_mapping.
    """

    def __init__(self, bot_token: str, router: MessageRouter) -> None:
        self._token = bot_token
        self._router = router
        self._bot = None       # aiogram.Bot
        self._dispatcher = None  # aiogram.Dispatcher

    async def start(self) -> None:
        """Start the Telegram bot with long-polling.

        Registers message handlers and begins polling for updates.
        """
        logger.info("telegram.start")
        # TODO: implement Telegram bot startup
        # 1. from aiogram import Bot, Dispatcher
        # 2. self._bot = Bot(token=self._token)
        # 3. self._dispatcher = Dispatcher()
        # 4. Register handler: @dp.message() → self._handle_message
        # 5. await self._dispatcher.start_polling(self._bot)
        raise NotImplementedError("Telegram start not yet implemented")

    async def stop(self) -> None:
        """Stop the Telegram bot gracefully."""
        logger.info("telegram.stop")
        # TODO: implement
        # await self._dispatcher.stop_polling()
        # await self._bot.session.close()

    async def send(self, message: OutgoingMessage) -> None:
        """Send a message to a Telegram user.

        Args:
            message: Formatted response with channel_user_id = Telegram chat_id.
        """
        logger.info(
            "telegram.send",
            chat_id=message.channel_user_id,
            text_length=len(message.text),
        )
        # TODO: implement
        # await self._bot.send_message(
        #     chat_id=int(message.channel_user_id),
        #     text=message.text,
        #     reply_to_message_id=int(message.thread_id) if message.thread_id else None,
        # )
        raise NotImplementedError("Telegram send not yet implemented")

    async def _handle_message(self, tg_message: object) -> None:
        """Handle an incoming Telegram message.

        Converts aiogram Message to IncomingMessage, routes it,
        and sends the response back.
        """
        # TODO: implement message handling
        # 1. Extract: chat_id, user_id, text, message_id from tg_message
        # 2. Build IncomingMessage(channel="telegram", ...)
        # 3. response = await self._router.route(incoming)
        # 4. await self.send(response)
        raise NotImplementedError("Telegram message handler not yet implemented")
