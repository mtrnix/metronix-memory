"""Prompt assembly helpers for the ASOC chat orchestrator (MTRNIX-354, T4).

All functions are pure (no I/O, no async) — they are called synchronously
inside the orchestrator.

Functions:
    build_system_prompt — compose system prompt with MCP tool schema listing.
    assemble_history    — merge DB messages + request-body history into OpenAI format,
                          capped by turn count and token budget.
    assemble_context    — format filtered MergedResult chunks into an LLM context string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from metatron.chat.models import ChatMessage
    from metatron.integrations.asoc_mcp_client import AsocToolDescriptor

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are an AI assistant helping a TRON.ASOC user answer questions about \
the project "{project_name}". Use ONLY the provided context from the \
project index and the results of any tools you invoke.
HARD RULES:
1. If the context does not contain enough information, say so explicitly: \
"I do not have data for this question. Please check via the ASOC UI." \
Never fabricate facts.
2. Mark every factual claim with a citation marker [N], where N is the \
source number. Return sources by invoking the cite_source tool.
3. Rely only on the current context. Do not produce general knowledge \
about vulnerabilities that is not present in the context.
4. Do not perform actions (status changes, scan triggers, etc.) — you \
are operating in read-only mode.
Tools available for live data lookups:
{mcp_tools_schema}
"""


def build_system_prompt(
    project_name: str,
    mcp_tools: list[AsocToolDescriptor],
) -> str:
    """Return the system prompt for the ASOC chat LLM.

    Args:
        project_name: Human-readable project name injected into the prompt header.
        mcp_tools:    Whitelisted MCP tools available in this session.
    """
    if mcp_tools:
        tools_text = "\n".join(f"- {t.name}: {t.description}" for t in mcp_tools)
    else:
        tools_text = "(no live tools available)"
    return SYSTEM_PROMPT_TEMPLATE.format(
        project_name=project_name,
        mcp_tools_schema=tools_text,
    )


# ---------------------------------------------------------------------------
# History assembly
# ---------------------------------------------------------------------------

_TOKENS_PER_WORD_APPROX = 0.75  # cheap approximation: tokens ≈ words / 0.75


def _estimate_tokens(text: str) -> int:
    """Estimate token count via word count (cheap approximation)."""
    return max(1, int(len(text.split()) / _TOKENS_PER_WORD_APPROX))


def _message_to_oai(msg: ChatMessage) -> dict[str, str]:
    """Convert a :class:`ChatMessage` domain object to an OpenAI chat dict."""
    return {"role": str(msg.role), "content": msg.content}


def assemble_history(
    db_messages: list[ChatMessage],
    body_history: list[dict[str, Any]] | None,
    *,
    max_turns: int,
    max_tokens: int,
) -> list[dict[str, str]]:
    """Assemble conversation history for injection into the LLM request.

    DB messages are authoritative (they represent the persisted truth).
    ``body_history`` from the request is supplementary — it is appended only
    if it contains messages not already covered by ``db_messages``.

    Caps applied (in order):
    1. Keep at most ``2 * max_turns`` messages (user + assistant per turn).
    2. Drop oldest messages until the estimated total is ≤ ``max_tokens``.

    Returns the remaining messages in chronological order (oldest → newest).
    """
    # Convert DB messages first.
    history: list[dict[str, str]] = [_message_to_oai(m) for m in db_messages]

    # Append supplementary body history (de-dup by content equality is impractical
    # here — body_history is a client-side convenience for retries/reconnects).
    if body_history:
        for item in body_history:
            role = item.get("role", "")
            content = item.get("content", "")
            if role and content:
                history.append({"role": str(role), "content": str(content)})

    # Cap by turn count (2 messages per turn).
    cap = 2 * max_turns
    if len(history) > cap:
        history = history[-cap:]

    # Cap by token budget: drop oldest messages first.
    while history and sum(_estimate_tokens(m["content"]) for m in history) > max_tokens:
        history.pop(0)

    return history


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

_MAX_CHARS_PER_CHUNK = 2000


def assemble_context(filtered_results: list[Any], max_chars: int) -> str:
    """Format filtered MergedResult dicts into an LLM context string.

    Each chunk is rendered as a numbered markdown section.  Chunks are
    truncated at :data:`_MAX_CHARS_PER_CHUNK` characters.  The total context
    is truncated at ``max_chars`` characters (whole-chunk granularity —
    a chunk is either fully included or fully excluded).

    Args:
        filtered_results: List of ``MergedResult`` dicts as returned by
            :class:`~metatron.integrations.asoc_visibility.AsocVisibilityFilter`.
        max_chars: Soft cap on total context size (characters).

    Returns:
        Formatted context string ready to prefix the user's question.
    """
    sections: list[str] = []
    total = 0

    for idx, mr in enumerate(filtered_results, start=1):
        memory = mr.get("memory", {}) if isinstance(mr, dict) else {}
        payload = memory.get("payload", {}) if isinstance(memory, dict) else {}

        # Prefer top-level fields, fall back to payload.
        title = memory.get("title") or payload.get("title") or "Untitled"
        source_type = memory.get("source_type") or payload.get("source_type") or "unknown"
        entity_id = memory.get("entity_id") or payload.get("entity_id") or memory.get("id") or ""
        content: str = memory.get("content") or payload.get("content") or ""
        if len(content) > _MAX_CHARS_PER_CHUNK:
            content = content[:_MAX_CHARS_PER_CHUNK]

        section = (
            f"## [{idx}] {title} ({source_type}"
            + (f", {entity_id}" if entity_id else "")
            + f")\n{content}\n"
        )

        if total + len(section) > max_chars:
            break

        sections.append(section)
        total += len(section)

    return "\n".join(sections)
