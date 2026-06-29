"""Slash commands — /search, /sync, /skills, /help, etc.

These are handled before the LLM router. Fast, deterministic responses.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

HELP_TEXT = """Available commands:
/search <query> — Search the knowledge base
/sync — Trigger a sync of all connected sources
/skills — List available skills
/connections — List configured connections
/help — Show this help message"""


async def parse_command(text: str) -> str | None:
    """Parse slash commands from user input.

    Args:
        text: Raw message text.

    Returns:
        Response string if command matched, None otherwise.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped.split(maxsplit=1)
    command = parts[0].lower()
    # arg = parts[1] if len(parts) > 1 else ""

    logger.info("commands.parse", command=command)

    if command == "/help":
        return HELP_TEXT

    # TODO: implement other commands
    # /search <query> → trigger retrieval and return results
    # /sync → trigger connector sync for workspace
    # /skills → list available skills from DB
    # /connections → list configured connections
    if command == "/search":
        return "Search command is not yet implemented."
    if command == "/sync":
        return "Sync command is not yet implemented."
    if command == "/skills":
        return "Skills listing is not yet implemented."
    if command == "/connections":
        return "Connections listing is not yet implemented."

    return f"Unknown command: {command}. Type /help for available commands."
