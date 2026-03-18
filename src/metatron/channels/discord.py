"""Discord channel adapter — discord.py integration.

Receives DM messages via gateway. Routes through AgentRouter
using asyncio.to_thread() since the router is sync. Handles typing
indicator, long message splitting, and file uploads.
"""

from __future__ import annotations

import asyncio

import discord
import structlog

from typing import Any

from metatron.agent.router import AgentRouter

logger = structlog.get_logger()

# Discord message length limit
_DC_MAX_LENGTH = 2000


class DiscordChannel:
    """Discord bot channel using discord.py.

    Listens for DM messages, routes through AgentRouter (sync)
    via asyncio.to_thread(), sends responses back.
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

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register discord.py event handlers."""

        @self._client.event
        async def on_ready() -> None:
            logger.info(
                "discord.ready",
                user=str(self._client.user),
                user_id=self._client.user.id if self._client.user else None,
            )

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            # Ignore own messages
            if message.author == self._client.user:
                return
            # Only respond to DMs
            if not isinstance(message.channel, discord.DMChannel):
                return
            # Handle attachments
            if message.attachments:
                await self._handle_attachments(message)
                return
            # Handle text
            if message.content:
                await self._handle_message(message)

    async def start(self) -> None:
        """Start the Discord bot."""
        logger.info("discord.starting")
        await self._client.start(self._token)

    async def stop(self) -> None:
        """Stop the Discord bot gracefully."""
        logger.info("discord.stop")
        await self._client.close()

    async def _handle_message(self, message: discord.Message) -> None:
        """Handle an incoming DM text message."""
        user_id = str(message.author.id)
        text = message.content.strip()

        logger.info(
            "discord.message.received",
            user_id=user_id,
            text_len=len(text),
        )

        if self._mapper:
            display_name = message.author.display_name or message.author.name
            user = await self._mapper.map_platform_user(
                channel="discord",
                channel_user_id=str(message.author.id),
                workspace_id=self._workspace_id,
                event_bus=self._event_bus,
                display_name=display_name,
            )
            if user:
                user_id = user.id

        async with message.channel.typing():
            try:
                answer = await asyncio.to_thread(
                    self._router.route,
                    text=text,
                    user_id=user_id,
                    workspace_id=self._workspace_id,
                )
            except Exception as e:
                logger.error("discord.route.error", error=str(e), exc_info=True)
                answer = "Something went wrong. The error has been logged."

        await self._send_response(message.channel, answer)

    async def _handle_attachments(self, message: discord.Message) -> None:
        """Handle file uploads from Discord DM."""
        user_id = str(message.author.id)

        for attachment in message.attachments:
            logger.info(
                "discord.document.received",
                user_id=user_id,
                filename=attachment.filename,
                file_size=attachment.size,
            )

            async with message.channel.typing():
                try:
                    content = await attachment.read()
                except Exception as e:
                    logger.error(
                        "discord.document.download_error",
                        error=str(e), exc_info=True,
                    )
                    await self._send_response(
                        message.channel,
                        "Could not download the file. Please try again.",
                    )
                    continue

                try:
                    answer = await asyncio.to_thread(
                        self._router.handle_file_upload,
                        content=content,
                        filename=attachment.filename,
                        user_id=user_id,
                        workspace_id=self._workspace_id,
                    )
                except Exception as e:
                    logger.error(
                        "discord.document.error", error=str(e), exc_info=True,
                    )
                    answer = "Something went wrong. The error has been logged."

            await self._send_response(message.channel, answer)

    async def _send_response(
        self,
        channel: discord.DMChannel,
        text: str,
    ) -> None:
        """Send a response, splitting long messages at Discord's 2000 char limit."""
        chunks = _split_message(text)
        for chunk in chunks:
            try:
                await channel.send(chunk)
            except Exception as e:
                logger.error(
                    "discord.send.error",
                    channel_id=channel.id,
                    error=str(e),
                )


def _split_message(text: str, max_length: int = _DC_MAX_LENGTH) -> list[str]:
    """Split a long message into Discord-safe chunks.

    Tries to split at paragraph boundaries first, then line breaks,
    then spaces, then hard-splits.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_pos = remaining.rfind("\n\n", 0, max_length)
        if split_pos == -1:
            split_pos = remaining.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = remaining.rfind(" ", 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip("\n")

    return chunks
