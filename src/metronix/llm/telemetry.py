"""LLM generation telemetry context and emission (PROJ-336).

This module owns the per-request TelemetryContext ContextVar, the
``set_telemetry_context`` context-manager helper used by entry-points
(REST, MCP, ingestion, freshness), the ``update_retrieved_context`` mutator
called just before the RAG-answer LLM call, and the synchronous ``emit_log``
that writes one row to ``llm_generation_log``.

Design constraints
------------------
* ``emit_log`` is **fully synchronous** — ``chat_completion`` runs inside
  ``asyncio.to_thread`` (no event loop in the calling thread), so
  ``asyncio.create_task`` would raise RuntimeError. The insert goes via
  ``storage.pg_connection.get_session()`` (psycopg2) in the same thread.
* The module never raises from ``emit_log`` — any write failure is logged at
  WARNING and silently discarded.
* The opt-out cache is protected by ``threading.Lock`` (sync code path).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from metronix.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from uuid import UUID

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# TelemetryContext dataclass — mutable so update_retrieved_context can patch
# the current instance in-place without resetting the ContextVar token.
# ---------------------------------------------------------------------------


@dataclass
class TelemetryContext:
    """Mutable per-request telemetry context propagated via ContextVar."""

    workspace_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    source: str | None = None
    correlation_id: UUID | None = None
    retrieved_context: str | None = None
    extra_metadata: dict[str, Any] | None = None


# Module-level ContextVar — isolated per asyncio Task and per thread.
current_telemetry_ctx: ContextVar[TelemetryContext | None] = ContextVar(
    "current_telemetry_ctx", default=None
)


# ---------------------------------------------------------------------------
# Context manager for entry-points
# ---------------------------------------------------------------------------


@contextmanager
def set_telemetry_context(
    *,
    workspace_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    source: str | None = None,
    correlation_id: UUID | None = None,
) -> Generator[TelemetryContext, None, None]:
    """Push a fresh TelemetryContext onto the ContextVar for the duration of the block.

    Nested usage: the child scope replaces the parent for its duration; on exit
    the parent's token is restored.  The child does NOT inherit the parent's
    ``retrieved_context`` — each scope starts clean.
    """
    ctx = TelemetryContext(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        source=source,
        correlation_id=correlation_id,
    )
    token: Token[TelemetryContext | None] = current_telemetry_ctx.set(ctx)
    try:
        yield ctx
    finally:
        current_telemetry_ctx.reset(token)


# ---------------------------------------------------------------------------
# Mutator — called just before the RAG-answer LLM call
# ---------------------------------------------------------------------------


def update_retrieved_context(text: str) -> None:
    """Set retrieved_context on the current TelemetryContext instance.

    No-op when no context is active.
    """
    ctx = current_telemetry_ctx.get()
    if ctx is not None:
        ctx.retrieved_context = text


def add_extra_metadata(**kv: Any) -> None:
    """Merge keys into ``extra_metadata`` on the current TelemetryContext.

    Safer than ``current_telemetry_ctx.get().extra_metadata = {...}``: assign
    obliterates whatever a previous call site wrote. This helper merges, so
    multiple call sites in the same scope (search.py setting subtype/lang,
    neo4j_graph.py setting doc_label) can coexist.

    No-op when no context is active.
    """
    ctx = current_telemetry_ctx.get()
    if ctx is None:
        return
    if ctx.extra_metadata is None:
        ctx.extra_metadata = {}
    ctx.extra_metadata.update(kv)


# ---------------------------------------------------------------------------
# Opt-out cache (workspace-level, TTL-based, threading.Lock guarded)
# ---------------------------------------------------------------------------

# {workspace_id: (opt_out: bool, fetched_at: float)}
_opt_out_cache: OrderedDict[str, tuple[bool, float]] = OrderedDict()
# Coarse lock guarding the cache dict and the per-workspace lock dict below.
_opt_out_cache_lock = threading.Lock()
# Per-workspace locks ensure N concurrent misses on the same workspace_id
# issue ONE PG SELECT, not N — without blocking misses on other workspaces.
# Bounded LRU prevents unbounded growth on deployments with many short-lived
# workspaces (ephemeral test fixtures, future per-agent tenants, etc).
_opt_out_per_ws_locks: OrderedDict[str, threading.Lock] = OrderedDict()
_OPT_OUT_LOCK_CAP = 1024


def _get_per_ws_lock(workspace_id: str) -> threading.Lock:
    """Return the lock for ``workspace_id``, creating it if needed.

    Uses a bounded LRU: when the dict exceeds ``_OPT_OUT_LOCK_CAP`` entries,
    the least-recently-used lock is dropped. An evicted lock that is still
    being held by a concurrent caller stays alive via the holder's local
    reference; the next caller for that workspace creates a fresh lock and
    the old one is GC'd when the holder releases it. Worst case is two
    callers briefly racing on a cold workspace — no correctness issue.
    """
    with _opt_out_cache_lock:
        lock = _opt_out_per_ws_locks.get(workspace_id)
        if lock is None:
            lock = threading.Lock()
            _opt_out_per_ws_locks[workspace_id] = lock
            if len(_opt_out_per_ws_locks) > _OPT_OUT_LOCK_CAP:
                _opt_out_per_ws_locks.popitem(last=False)
        else:
            _opt_out_per_ws_locks.move_to_end(workspace_id)
        return lock


def _is_opted_out(workspace_id: str) -> bool:
    """Return True if the workspace has llm_telemetry_opt_out=true.

    Uses a TTL cache to avoid a PG round-trip on every LLM call. Concurrent
    misses on the same ``workspace_id`` are serialised by a per-workspace
    lock that is held across the SELECT — so a thundering herd of N callers
    issues exactly one query; the (N-1) followers read the freshly-populated
    cache entry on entry into the critical section.
    """
    settings = get_settings()
    ttl = settings.llm_telemetry_opt_out_cache_ttl_seconds
    now = time.monotonic()

    # Fast path — read cache without holding the per-ws lock.
    with _opt_out_cache_lock:
        entry = _opt_out_cache.get(workspace_id)
    if entry is not None:
        opt_out, fetched_at = entry
        if now - fetched_at < ttl:
            return opt_out

    # Slow path — acquire the per-workspace lock so only one caller queries PG.
    ws_lock = _get_per_ws_lock(workspace_id)
    with ws_lock:
        # Re-check under the lock — another waiter may have populated the entry.
        now = time.monotonic()
        with _opt_out_cache_lock:
            entry = _opt_out_cache.get(workspace_id)
        if entry is not None:
            opt_out, fetched_at = entry
            if now - fetched_at < ttl:
                return opt_out

        # Still missing — issue the SELECT.
        try:
            from metronix.storage.pg_connection import get_session
            from metronix.storage.pg_models import WorkspaceRow

            with get_session() as session:
                row = session.query(WorkspaceRow).filter_by(id=workspace_id).first()
                opt_out = bool(row.llm_telemetry_opt_out) if row is not None else False
        except Exception as exc:
            logger.warning(
                "llm_telemetry.opt_out_check_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            # Fail open — write the row so we don't lose data on transient DB errors.
            return False

        with _opt_out_cache_lock:
            _opt_out_cache[workspace_id] = (opt_out, time.monotonic())

        return opt_out


# ---------------------------------------------------------------------------
# Public predicate — callers can use this as a fast-path check before doing
# expensive prompt-snapshot work. Note: ``emit_log`` itself takes a callable
# for ``messages``, so most call sites do NOT need to gate manually — the
# snapshot is built only after the opt-out re-check inside emit_log. This
# helper is kept for diagnostic / introspection use.
# ---------------------------------------------------------------------------


def is_telemetry_writable() -> bool:
    """Return True iff a row produced now would actually be written.

    Cheap path: kill-switch check + opt-out cache lookup. Workspace_id is
    read from the ambient :data:`current_telemetry_ctx`; when missing the
    function returns True (writes proceed with ``workspace_id IS NULL`` so
    the data is not lost).
    """
    settings = get_settings()
    if not settings.llm_telemetry_enabled:
        return False
    ctx = current_telemetry_ctx.get()
    if ctx is None or not ctx.workspace_id:
        return True
    return not _is_opted_out(ctx.workspace_id)


# ---------------------------------------------------------------------------
# emit_log — the main entry point called by chat_completion()
# ---------------------------------------------------------------------------


# Maximum per-message-content / response-content size in characters. Anything
# larger is truncated and flagged in metadata. 8 000 matches the NER text
# truncation in storage/neo4j_graph.py:extract_graph_from_text so an
# ner_extraction prompt that hit the upstream cap is always small enough to
# fit; chosen as a single cap for simplicity (oversized rag_answer prompts get
# the same treatment — fine for the FT dataset; full context is reconstructible
# from retrieved_context + the upstream document store anyway).
_MAX_CONTENT_CHARS = 8_000


def _cap_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Cap each message's content to ``_MAX_CONTENT_CHARS``.

    Returns ``(capped_messages, truncated)`` — ``truncated`` is True iff at
    least one message was shortened. The capped copy is a fresh list so the
    caller's original list is untouched.
    """
    capped: list[dict[str, Any]] = []
    truncated = False
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str) and len(content) > _MAX_CONTENT_CHARS:
            new = dict(m)
            new["content"] = content[:_MAX_CONTENT_CHARS]
            capped.append(new)
            truncated = True
        else:
            capped.append(m)
    return capped, truncated


def _cap_response(text: str | None) -> tuple[str | None, bool]:
    """Cap response content to ``_MAX_CONTENT_CHARS``. Returns ``(text, truncated)``."""
    if text is None:
        return None, False
    if len(text) > _MAX_CONTENT_CHARS:
        return text[:_MAX_CONTENT_CHARS], True
    return text, False


def emit_log(
    *,
    call_site: str,
    provider: str,
    model: str,
    messages: list[dict[str, Any]] | Callable[[], list[dict[str, Any]]],
    response: Any | None,  # LLMResponse | None — typed as Any to avoid circular import
    latency_ms: int,
    success: bool,
    error_class: str | None,
    error_message: str | None,
    fallback_used: bool,
    fallback_provider: str | None,
) -> None:
    """Write one telemetry row to llm_generation_log.

    Fully synchronous.  Never raises — all exceptions are caught and logged.

    Args:
        call_site: Identifier string from the audit table (e.g. "rag_answer").
        provider: Provider name (e.g. "ollama", "deepseek").
        model: Model name as returned by the provider.
        messages: The request messages — either an already-built list of
            serialisable dicts, OR a zero-argument callable that builds it.
            Passing a callable lets the caller defer materialisation until
            AFTER the kill-switch / opt-out re-check, so a prompt copy never
            lives in process memory when the workspace has opted out
            mid-call (closes the race window on the entry-time gate).
        response: LLMResponse on success, None on failure.
        latency_ms: Wall-clock ms for the LLM call.
        success: True if the provider returned non-empty content.
        error_class: Exception class name on failure (or "EmptyResponse").
        error_message: Short error text, already truncated to ≤512 chars.
        fallback_used: True when the primary provider failed and fallback ran.
        fallback_provider: Fallback provider name when fallback_used=True.
    """
    settings = get_settings()
    if not settings.llm_telemetry_enabled:
        return

    # Read the ambient ContextVar.
    ctx = current_telemetry_ctx.get()
    workspace_id = ctx.workspace_id if ctx is not None else None
    user_id = ctx.user_id if ctx is not None else None
    agent_id = ctx.agent_id if ctx is not None else None
    source = ctx.source if ctx is not None else None
    correlation_id = ctx.correlation_id if ctx is not None else None
    retrieved_context = ctx.retrieved_context if ctx is not None else None
    extra_metadata = dict(ctx.extra_metadata) if ctx is not None and ctx.extra_metadata else {}

    # Per-workspace opt-out — checked BEFORE we materialise the prompt
    # snapshot, so when the workspace has opted out the prompt copy never
    # leaves the upstream Message-object list. Callers passing a callable
    # for ``messages`` rely on this gate for the "we don't process" privacy
    # posture; callers passing a pre-built list also benefit (we still drop
    # the row, just at the cost of one extra in-memory copy upstream).
    if workspace_id is not None and _is_opted_out(workspace_id):
        return

    # Materialise the request messages list (deferred construction — see docstring).
    raw_messages = messages() if callable(messages) else messages
    capped_messages, message_truncated = _cap_messages(raw_messages)

    # Token counts via property accessors (always return int, default 0).
    if response is not None:
        prompt_tokens: int = response.prompt_tokens
        completion_tokens: int = response.completion_tokens
        total_tokens: int = response.total_tokens
        raw_response_content: str | None = response.content if success else None
    else:
        prompt_tokens = completion_tokens = total_tokens = 0
        raw_response_content = None

    response_content, response_truncated = _cap_response(raw_response_content)
    zero_tokens = total_tokens == 0 and prompt_tokens == 0 and completion_tokens == 0

    # Build metadata JSONB.
    metadata: dict[str, Any] = {
        "fallback_used": fallback_used,
        "fallback_provider": fallback_provider,
        "zero_tokens": zero_tokens,
        **extra_metadata,
    }
    if message_truncated:
        metadata["message_truncated"] = True
    if response_truncated:
        metadata["response_truncated"] = True
    if retrieved_context is not None and call_site == "rag_answer":
        # retrieved_context is also capped — same rationale as request/response content.
        ctx_capped, ctx_truncated = _cap_response(retrieved_context)
        metadata["retrieved_context"] = ctx_capped
        if ctx_truncated:
            metadata["retrieved_context_truncated"] = True

    try:
        from metronix.storage.llm_generation_log import LLMLogRowData, insert_log_row_sync

        row = LLMLogRowData(
            call_site=call_site,
            source=source,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=agent_id,
            correlation_id=str(correlation_id) if correlation_id is not None else None,
            provider=provider,
            model=model,
            request_messages=capped_messages,
            response_content=response_content,
            prompt_tokens=prompt_tokens if prompt_tokens else None,
            completion_tokens=completion_tokens if completion_tokens else None,
            total_tokens=total_tokens if total_tokens else None,
            latency_ms=latency_ms,
            success=success,
            error_class=error_class,
            error_message=error_message,
            metadata=metadata,
        )
        insert_log_row_sync(row)
    except Exception as exc:
        logger.warning(
            "llm_telemetry.write_failed",
            call_site=call_site,
            provider=provider,
            error=str(exc),
        )
