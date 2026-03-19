"""Channels layer — messenger adapters. Depends on core + agent."""

from metatron.channels.discord import DiscordChannel
from metatron.channels.manager import ChannelManager
from metatron.channels.slack import SlackChannel
from metatron.channels.telegram import TelegramChannel

__all__ = [
    "ChannelManager",
    "DiscordChannel",
    "SlackChannel",
    "TelegramChannel",
]
