"""Translation utilities for multilingual support.

Uses the configured LLM provider to translate text between Russian
and English. Falls back to the original text on any error.
"""

from __future__ import annotations

import structlog

from metatron.llm import chat_completion  # TODO: async migration

logger = structlog.get_logger()


def is_russian(text: str) -> bool:
    """Return ``True`` if *text* contains Cyrillic characters."""
    return any("\u0400" <= c <= "\u04ff" for c in text)


def is_english(text: str) -> bool:
    """Return ``True`` if *text* is primarily English (Latin characters)."""
    latin_count = sum(1 for c in text if "a" <= c.lower() <= "z")
    return latin_count > len(text) * 0.3


def translate_to_english(text: str) -> str:  # TODO: async migration
    """Translate text to English using the configured LLM provider.

    Returns the original text if it is already English or if translation fails.
    """
    if not text or not is_russian(text):
        return text

    try:
        result = chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the following text to English. "
                        "Preserve formatting, names, and technical terms. "
                        "Return ONLY the translation."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=4000,
            timeout=60,
        )
        return result.strip()
    except Exception:
        logger.warning("translation.to_english.failed", text_length=len(text))
    return text


def translate_to_russian(text: str) -> str:  # TODO: async migration
    """Translate text to Russian using the configured LLM provider.

    Returns the original text if it is already Russian or if translation fails.
    """
    if not text or is_russian(text):
        return text

    try:
        result = chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the following text to Russian. Return ONLY the translation."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=200,
            timeout=10,
        )
        return result.strip()
    except Exception:
        logger.warning("translation.to_russian.failed", text_length=len(text))
    return text
