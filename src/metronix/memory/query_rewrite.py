"""Query-rewrite stage for the assembler (MTRNIX-372).

Default = last user message. Optional SLM rewrite (behind a flag) when the
rule heuristic says the tail message is too short or pronoun-heavy to search
on its own. SLM call runs in a thread (the provider is synchronous) under an
asyncio timeout; on timeout/error we fall back to the last user message.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable  # noqa: TC003
from typing import TYPE_CHECKING, Any

import structlog

from metronix.llm.base import Message
from metronix.llm.provider import create_provider

if TYPE_CHECKING:
    from metronix.core.config import Settings
    from metronix.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

_PRONOUNS = {"it", "this", "that", "they", "them", "those", "these", "he", "she"}
_REWRITE_SYSTEM = (
    "Rewrite the user's latest message into a single standalone search query "
    "using the conversation context. Output ONLY the query, no preamble."
)


def last_user_message(messages: list[dict[str, Any]]) -> str:
    """Return the content of the last role=='user' message, or ''."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _needs_rewrite(text: str) -> bool:
    """Heuristic: short (<5 words) OR contains a context pronoun."""
    words = re.findall(r"\w+", text.lower())
    if len(words) < 5:
        return True
    return any(w in _PRONOUNS for w in words)


class QueryRewriter:
    """Builds a memory-search query from chat messages."""

    def __init__(
        self,
        *,
        settings: Settings,
        provider_factory: Callable[[], LLMProvider] | None = None,
    ) -> None:
        self._settings = settings
        self._provider_factory = provider_factory or self._default_provider_factory

    def _default_provider_factory(self) -> LLMProvider:
        s = self._settings
        if s.freshness_llm_provider:
            # Dedicated aux/SLM endpoint explicitly configured.
            return create_provider(
                provider_name=s.freshness_llm_provider,
                model=s.freshness_llm_model,
            )
        # Fall back to the main provider AND its own configured model, so an
        # all-local install requests the model that is actually pulled.
        return create_provider(
            provider_name=s.llm_provider,
            model=s.model_for_provider(s.llm_provider),
        )

    async def rewrite(
        self, messages: list[dict[str, Any]], *, timeout_s: float
    ) -> tuple[str, bool, bool]:
        """Return (query, used_slm, fallback)."""
        tail = last_user_message(messages)
        if not self._settings.proxy_query_rewrite_enabled or not _needs_rewrite(tail):
            return tail, False, False

        context_msgs = [
            Message(role="system", content=_REWRITE_SYSTEM),
            *[
                Message(
                    role=str(m.get("role", "user")),
                    content=str(m.get("content") or ""),
                )
                for m in messages[-3:]
            ],
        ]
        try:
            provider = self._provider_factory()
            resp = await asyncio.wait_for(
                asyncio.to_thread(provider.chat_completion, context_msgs, temperature=0.0),
                timeout=timeout_s,
            )
            rewritten = (resp.content or "").strip()
            if not rewritten:
                return tail, False, True
            return rewritten, True, False
        except Exception as exc:  # noqa: BLE001 — fail open to rule
            logger.warning("query_rewrite.fallback", error=str(exc))
            return tail, False, True
