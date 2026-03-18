"""Telegram channel adapter — aiogram 3.x bot integration.

Receives messages via long-polling (MVP). Routes through AgentRouter
using asyncio.to_thread() since the router is sync. Handles typing
indicator, long message splitting, and Markdown→HTML→plain fallback.
"""

from __future__ import annotations

import asyncio
import re

import structlog
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode

from typing import Any

from metatron.agent.router import AgentRouter

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
        workspace_id: str | None = None,
        mapper: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._token = bot_token
        self._router = router
        self._workspace_id = (
            workspace_id or router._settings.default_workspace_id
        )
        self._mapper = mapper
        self._event_bus = event_bus
        self._bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self._dp = Dispatcher()
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register aiogram message and error handlers."""

        @self._dp.errors()
        async def on_error(event: types.ErrorEvent) -> bool:
            """Global error handler — prevents raw tracebacks from reaching users."""
            logger.error(
                "telegram.unhandled_error",
                error=str(event.exception),
                exc_info=event.exception,
            )
            try:
                if event.update and event.update.message:
                    await event.update.message.answer(
                        "Something went wrong. The error has been logged."
                    )
            except Exception:
                logger.warning("telegram.error_handler.reply_failed", exc_info=True)
            return True

        @self._dp.message(F.document)
        async def on_document(message: types.Message) -> None:
            await self._handle_document(message)

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

    async def _handle_document(self, message: types.Message) -> None:
        """Handle a file upload from Telegram."""
        doc = message.document
        if not doc:
            return

        chat_id = message.chat.id
        user_id = str(message.from_user.id) if message.from_user else str(chat_id)
        filename = doc.file_name or "unknown"

        logger.info(
            "telegram.document.received",
            chat_id=chat_id,
            user_id=user_id,
            filename=filename,
            file_size=doc.file_size,
        )

        await self._bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # Download file
        try:
            file_obj = await self._bot.get_file(doc.file_id)
            bio = await self._bot.download_file(file_obj.file_path)
            content = bio.read()
        except Exception as e:
            logger.error("telegram.document.download_error", error=str(e), exc_info=True)
            await self._send_response(chat_id, "Could not download the file. Please try again.")
            return

        # Process through router (sync)
        try:
            answer = await asyncio.to_thread(
                self._router.handle_file_upload,
                content=content,
                filename=filename,
                user_id=user_id,
                workspace_id=self._workspace_id,
            )
        except Exception as e:
            logger.error("telegram.document.error", error=str(e), exc_info=True)
            answer = "Something went wrong. The error has been logged."

        await self._send_response(chat_id, answer, reply_to=message.message_id)

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

        # Map platform user to internal user
        if self._mapper:
            display_name = ""
            if message.from_user:
                parts = [message.from_user.first_name or ""]
                if message.from_user.last_name:
                    parts.append(message.from_user.last_name)
                display_name = " ".join(parts).strip()
            user = await self._mapper.map_platform_user(
                channel="telegram",
                channel_user_id=user_id,
                workspace_id=self._workspace_id,
                event_bus=self._event_bus,
                display_name=display_name,
            )
            if user:
                user_id = user.id

        # Route through AgentRouter (sync) in a thread pool
        try:
            answer = await asyncio.to_thread(
                self._router.route,
                text=text,
                user_id=user_id,
                workspace_id=self._workspace_id,
            )
        except Exception as e:
            logger.error("telegram.route.error", error=str(e), exc_info=True)
            answer = "Something went wrong. The error has been logged."

        # Send response, splitting long messages
        await self._send_response(chat_id, answer, reply_to=message.message_id)

    async def _send_response(
        self, chat_id: int, text: str, reply_to: int | None = None,
    ) -> None:
        """Send a response with 3-step fallback: Markdown → HTML → plain text."""
        chunks = _split_message(text)

        for i, chunk in enumerate(chunks):
            reply_id = reply_to if i == 0 else None
            # Step 1: try Markdown
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_id,
                    parse_mode=ParseMode.MARKDOWN,
                )
                continue
            except Exception:
                pass
            # Step 2: try HTML (keeps basic formatting)
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=_markdown_to_html(chunk),
                    reply_to_message_id=reply_id,
                    parse_mode=ParseMode.HTML,
                )
                continue
            except Exception:
                pass
            # Step 3: plain text
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_to_message_id=reply_id,
                    parse_mode=None,
                )
            except Exception as e:
                logger.error("telegram.send.error", chat_id=chat_id, error=str(e))


def _markdown_to_html(text: str) -> str:
    """Convert common Markdown to Telegram-compatible HTML.

    Used as a fallback when Telegram's Markdown parser rejects LLM output.
    HTML is more forgiving and preserves basic formatting.
    """
    # Code blocks first (before inline code)
    text = re.sub(r"```\w*\n?(.*?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* (but not inside already-converted tags)
    text = re.sub(r"(?<![<\w])\*(?!\*)(.+?)(?<!\*)\*(?![>\w])", r"<i>\1</i>", text)
    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Headings: ### text → <b>text</b>
    text = re.sub(r"^#{1,6}\s+(.+)", r"<b>\1</b>", text, flags=re.MULTILINE)
    return text


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
