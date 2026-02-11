"""Slack channel adapter — slack-bolt integration.

Implements ChannelInterface. Uses slack-bolt for socket mode
event handling. Processes message events and app mentions.
"""

from __future__ import annotations

import structlog

from metatron.agent.router import AgentRouter
from metatron.core.interfaces import ChannelInterface
from metatron.core.models import IncomingMessage, OutgoingMessage

logger = structlog.get_logger()


class SlackChannel(ChannelInterface):
    """Slack bot adapter using slack-bolt.

    Uses Socket Mode for real-time events (no public URL needed).
    Handles message events and @mentions.
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        signing_secret: str,
        router: AgentRouter,
    ) -> None:
        self._bot_token = bot_token
        self._app_token = app_token
        self._signing_secret = signing_secret
        self._router = router
        self._app = None     # slack_bolt.async_app.AsyncApp
        self._handler = None  # slack_bolt.adapter.socket_mode.async_handler

    async def start(self) -> None:
        """Start the Slack bot in socket mode.

        Registers event listeners and connects via WebSocket.
        """
        logger.info("slack.start")
        # TODO: implement Slack bot startup
        # 1. from slack_bolt.async_app import AsyncApp
        # 2. from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        # 3. self._app = AsyncApp(token=bot_token, signing_secret=signing_secret)
        # 4. Register: @app.event("message") → self._handle_message
        # 5. self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        # 6. await self._handler.start_async()
        raise NotImplementedError("Slack start not yet implemented")

    async def stop(self) -> None:
        """Stop the Slack bot gracefully."""
        logger.info("slack.stop")
        # TODO: implement
        # await self._handler.close_async()

    async def send(self, message: OutgoingMessage) -> None:
        """Send a message to a Slack channel/user.

        Args:
            message: Response with channel_user_id = Slack channel ID.
        """
        logger.info(
            "slack.send",
            channel=message.channel_user_id,
            text_length=len(message.text),
        )
        # TODO: implement
        # await self._app.client.chat_postMessage(
        #     channel=message.channel_user_id,
        #     text=message.text,
        #     thread_ts=message.thread_id,
        # )
        raise NotImplementedError("Slack send not yet implemented")

    async def _handle_message(self, event: dict[str, object], say: object) -> None:
        """Handle a Slack message event.

        Ignores bot messages to prevent loops.
        Converts Slack event to IncomingMessage and routes it.
        """
        # TODO: implement message handling
        # 1. Check if event is from a bot (ignore)
        # 2. Extract: channel, user, text, thread_ts
        # 3. Build IncomingMessage(channel="slack", ...)
        # 4. response = await self._router.route(incoming)
        # 5. await say(text=response.text, thread_ts=...)
        raise NotImplementedError("Slack message handler not yet implemented")
