"""Channels layer — messenger adapters. Depends on core + agent."""

from metatron.channels.slack import SlackChannel
from metatron.channels.telegram import TelegramChannel

__all__ = ["TelegramChannel", "SlackChannel"]
