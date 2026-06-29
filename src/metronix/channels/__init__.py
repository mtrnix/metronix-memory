"""Channels layer — messenger adapters. Depends on core + agent."""

from metronix.channels.discord import DiscordChannel
from metronix.channels.manager import ChannelManager
from metronix.channels.slack import SlackChannel
from metronix.channels.telegram import TelegramChannel

__all__ = [
    "ChannelManager",
    "DiscordChannel",
    "SlackChannel",
    "TelegramChannel",
]
