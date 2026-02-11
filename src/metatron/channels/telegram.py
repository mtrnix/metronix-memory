"""Telegram channel adapter — aiogram 3.x bot integration.

Receives messages via long-polling (MVP). Routes through AgentRouter
using asyncio.to_thread() since the router is sync. Handles typing
indicator, long message splitting, and Markdown parse fallback.
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode

from metatron.agent.router import AgentRouter
from metatron.core.config import Settings

logger = structlog.get_logger()

# Telegram message length limit
_TG_MAX_LENGTH = 4096


class TelegramChannel:
    """Telegram bot channel using aiogram 3.x with long-polling.

    Routes messages through AgentRouter (sync) via asyncio.to_thread().
    Sends responses with MarkdownV2 fallback to plain text.
    """

    def __init__(
        self,
        bot_token: str,
        router: AgentRouter,
        settings: Settings | None = None,
    ) -> None:
        self._token = bot_token
        self._router = router
        self._settings = settings or Settings()
        self._bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self._dp = Dispatcher()
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register aiogram message handlers."""

        @self._dp.message()
        async def on_message(message: types.Message) -> None:
            await self._handle_message(message)

    async def start(self) -> None:
        """Start the Telegram bot with long-polling."""
        logger.info("telegram.start", bot_id=self._bot.id)
        await self._dp.start_polling(self._bot)

    async def stop(self) -> None:
        """Stop the Telegram bot gracefully."""
        logger.info("telegram.stop")
        await self._dp.stop_polling()
        await self._bot.session.close()

    async def _handle_message(self, message: types.Message) -> None:
        """Handle an incoming Telegram message."""
        if not message.text:
            return

        chat_id = message.chat.id
        user_id = str(message.from_user.id) if message.from_user else str(chat_id)
        text = message.text.strip()

        logger.info(
            "telegram.message.received",
            chat_id=chat_id,
            user_id=user_id,
            text_len=len(text),
        )

        # Show typing indicator
        await self._bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # Route through AgentRouter (sync) in a thread pool
        try:
            answer = await asyncio.to_thread(
                self._router.route,
                text=text,
                user_id=user_id,
                workspace_id=self._settings.default_workspace_id,
            )
        except Exception as e:
            logger.error("telegram.route.error", error=str(e))
            answer = f"An error occurred while processing your request: {e}"

        # Send response, splitting long messages
        await self._send_response(chat_id, answer, reply_to=message.message_id)

    async def _send_response(
        self, chat_id: int, text: str, reply_to: int | None = None,
    ) -> None:
        """Send a response, splitting long messages and handling Markdown errors."""
        chunks = _split_message(text)

        for i, chunk in enumerate(chunks):
            reply_id = reply_to if i == 0 else None
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_id,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                # Markdown parse failed — fall back to plain text
                try:
                    await self._bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        reply_to_message_id=reply_id,
                        parse_mode=None,
                    )
                except Exception as e:
                    logger.error("telegram.send.error", chat_id=chat_id, error=str(e))


def _split_message(text: str, max_length: int = _TG_MAX_LENGTH) -> list[str]:
    """Split a long message into Telegram-safe chunks.

    Tries to split at paragraph boundaries first, then at line boundaries,
    then hard-splits at max_length.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at a paragraph break
        split_pos = remaining.rfind("\n\n", 0, max_length)
        if split_pos == -1:
            # Try to split at a line break
            split_pos = remaining.rfind("\n", 0, max_length)
        if split_pos == -1:
            # Try to split at a space
            split_pos = remaining.rfind(" ", 0, max_length)
        if split_pos == -1:
            # Hard split
            split_pos = max_length

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip("\n")

    return chunks
