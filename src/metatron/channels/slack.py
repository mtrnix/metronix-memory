"""Slack channel adapter — slack-bolt Socket Mode integration.

Receives DM messages via Socket Mode (WebSocket, no public URL needed).
Routes through AgentRouter using asyncio.to_thread() since the router
is sync. Handles long message splitting and file uploads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from metatron.agent.router import AgentRouter
from metatron.core.config import Settings

logger = structlog.get_logger()

# Slack message length limit
_SLACK_MAX_LENGTH = 4000


class SlackChannel:
    """Slack bot channel using slack-bolt with Socket Mode.

    Listens for DM messages, routes through AgentRouter (sync)
    via asyncio.to_thread(), sends responses back.
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        router: AgentRouter,
        settings: Settings | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._app_token = app_token
        self._router = router
        self._settings = settings or Settings()

        self._app = AsyncApp(token=bot_token)
        self._handler: AsyncSocketModeHandler | None = None
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register slack-bolt event handlers."""

        @self._app.event("message")
        async def on_message(event: dict, say: Callable) -> None:
            # Ignore bot messages (including own)
            if event.get("bot_id") or event.get("subtype"):
                return

            # Only respond to DMs (im channel type)
            channel_type = event.get("channel_type", "")
            if channel_type != "im":
                return

            user_id = event.get("user", "unknown")
            text = (event.get("text") or "").strip()

            # Handle file uploads
            files = event.get("files")
            if files:
                await self._handle_files(files, user_id, say)
                return

            # Handle text messages
            if text:
                await self._handle_message(text, user_id, say)

    async def start(self) -> None:
        """Start the Slack bot in Socket Mode."""
        import logging as _logging

        logger.info("slack.starting")
        # Create a quiet logger for Socket Mode internals (PING/PONG noise)
        sm_logger = _logging.getLogger("slack_sdk.socket_mode")
        sm_logger.setLevel(_logging.WARNING)

        self._handler = AsyncSocketModeHandler(
            self._app,
            self._app_token,
        )
        self._handler.client.logger.setLevel(_logging.WARNING)
        await self._handler.start_async()

    async def stop(self) -> None:
        """Stop the Slack bot gracefully."""
        logger.info("slack.stop")
        if self._handler:
            await self._handler.close_async()

    async def _handle_message(
        self, text: str, user_id: str, say: Callable,
    ) -> None:
        """Handle an incoming DM text message."""
        logger.info(
            "slack.message.received",
            user_id=user_id,
            text_len=len(text),
        )

        try:
            answer = await asyncio.to_thread(
                self._router.route,
                text=text,
                user_id=user_id,
                workspace_id=self._settings.default_workspace_id,
            )
        except Exception as e:
            logger.error("slack.route.error", error=str(e), exc_info=True)
            answer = "Something went wrong. The error has been logged."

        await self._send_response(say, answer)

    async def _handle_files(
        self,
        files: list[dict],
        user_id: str,
        say: Callable,
    ) -> None:
        """Handle file uploads from Slack DM."""
        for file_info in files:
            filename = file_info.get("name", "unknown")
            file_size = file_info.get("size", 0)
            url = file_info.get("url_private_download") or file_info.get("url_private")

            logger.info(
                "slack.document.received",
                user_id=user_id,
                filename=filename,
                file_size=file_size,
            )

            if not url:
                await say("Could not get download URL for the file.")
                continue

            # Download file using bot token for auth
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {self._bot_token}"},
                        follow_redirects=True,
                    )
                    resp.raise_for_status()
                    content = resp.content
            except Exception as e:
                logger.error(
                    "slack.document.download_error",
                    error=str(e), exc_info=True,
                )
                await say("Could not download the file. Please try again.")
                continue

            try:
                answer = await asyncio.to_thread(
                    self._router.handle_file_upload,
                    content=content,
                    filename=filename,
                    user_id=user_id,
                    workspace_id=self._settings.default_workspace_id,
                )
            except Exception as e:
                logger.error(
                    "slack.document.error", error=str(e), exc_info=True,
                )
                answer = "Something went wrong. The error has been logged."

            await self._send_response(say, answer)

    async def _send_response(self, say: Callable, text: str) -> None:
        """Send a response, splitting long messages at Slack's 4000 char limit."""
        chunks = _split_message(text)
        for chunk in chunks:
            try:
                await say(chunk)
            except Exception as e:
                logger.error("slack.send.error", error=str(e))


def _split_message(text: str, max_length: int = _SLACK_MAX_LENGTH) -> list[str]:
    """Split a long message into Slack-safe chunks.

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
