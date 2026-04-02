"""Embedding cache backed by Ollama API.

Caches dense embeddings in a TTL cache to avoid redundant API calls
during high-volume operations (e.g., mass document indexing).

Thread-safe with lock protection on cache reads and writes.
"""
# TODO: migrate to use LLMProviderInterface.embed()

from __future__ import annotations

import re
import threading
import time

import structlog
from cachetools import TTLCache

from metatron.core.config import Settings
from metatron.core.http import get_http_session

logger = structlog.get_logger()

# Safety limits for Ollama embedding API (nomic-embed-text, 8192 token context).
# Cyrillic/CJK: ~2 tokens/char → 2000 chars ≈ 4000 tokens.
# Latin: ~0.7 tokens/char → 6000 chars ≈ 4200 tokens.
_MAX_EMBEDDING_CHARS_NON_LATIN = 2000
_MAX_EMBEDDING_CHARS_LATIN = 6000
_NON_LATIN_RE = re.compile(r"[^\x00-\x7F]")
_CONTEXT_LENGTH_RE = re.compile(r"context length", re.IGNORECASE)

# Maximum split recursion depth (1 text → up to 2^3 = 8 sub-chunks).
_MAX_SPLIT_DEPTH = 3


def _get_max_embedding_chars(text: str) -> int:
    """Adaptive char limit based on script: stricter for Cyrillic/CJK."""
    non_latin = len(_NON_LATIN_RE.findall(text[:500]))  # sample start
    ratio = non_latin / max(len(text[:500]), 1)
    return _MAX_EMBEDDING_CHARS_NON_LATIN if ratio > 0.3 else _MAX_EMBEDDING_CHARS_LATIN


def _is_context_length_error(resp) -> bool:
    """Check if Ollama response is a context length overflow."""
    if resp.status_code < 400:
        return False
    try:
        return bool(_CONTEXT_LENGTH_RE.search(resp.text))
    except Exception:
        return False


_settings = Settings()

_embedding_cache: TTLCache = TTLCache(
    maxsize=_settings.embedding_cache_maxsize,
    ttl=_settings.embedding_cache_ttl,
)
_embedding_cache_lock = threading.Lock()

_embedding_cache_hits = 0
_embedding_cache_misses = 0


class _ContextLengthError(Exception):
    """Raised when Ollama returns a context length overflow error."""


def _call_ollama_embedding(
    text: str,
    model: str,
    session,
    ollama_url: str,
) -> list[float]:
    """Call Ollama embedding API with transient-error retry (3 attempts).

    Raises _ContextLengthError on context overflow (not retried here).
    """
    for attempt in range(3):
        try:
            resp = session.post(
                f"{ollama_url}/api/embeddings",
                json={
                    "model": model,
                    "prompt": text,
                    "options": {"num_ctx": 8192},
                },
                timeout=30,
            )

            if _is_context_length_error(resp):
                raise _ContextLengthError(
                    f"context length exceeded ({len(text)} chars): {resp.text[:200]}"
                )

            if resp.status_code >= 500:
                logger.error(
                    "embedding.ollama_error",
                    status=resp.status_code,
                    body=resp.text,
                    model=model,
                )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except _ContextLengthError:
            raise
        except Exception as e:
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                logger.warning(
                    "embedding_retry",
                    attempt=f"{attempt + 1}/3",
                    error=str(e),
                )
            else:
                logger.error("embedding_failed", attempts=3, error=str(e))
                raise
    raise RuntimeError("unreachable")  # pragma: no cover


def get_cached_embedding(text: str, model: str = "nomic-embed-text:latest") -> list[float]:
    """Get a single dense embedding with caching.

    Used for search queries and entity resolution where a single vector
    is needed. Applies adaptive truncation to fit the embedding model
    context window.

    Thread-safe with lock protection.
    """
    # TODO: async migration
    global _embedding_cache_hits, _embedding_cache_misses

    cache_key = hash((text, model))

    with _embedding_cache_lock:
        if cache_key in _embedding_cache:
            _embedding_cache_hits += 1
            return _embedding_cache[cache_key]

    _embedding_cache_misses += 1

    # Safety truncation for single-embedding mode (queries)
    max_chars = _get_max_embedding_chars(text)
    if len(text) > max_chars:
        logger.warning(
            "embedding.truncated",
            original_chars=len(text),
            max_chars=max_chars,
            text_preview=text[:100],
        )
        text = text[:max_chars].rsplit(" ", 1)[0]

    session = get_http_session()
    ollama_url = _settings.ollama_host

    logger.debug(
        "embedding.request",
        model=model,
        text_len=len(text),
        text_preview=text[:100],
        ollama_url=ollama_url,
    )

    embedding = _call_ollama_embedding(text, model, session, ollama_url)

    with _embedding_cache_lock:
        _embedding_cache[cache_key] = embedding

    return embedding


def get_cached_embedding_split(
    text: str,
    model: str = "nomic-embed-text:latest",
    depth: int = 0,
) -> list[tuple[str, list[float]]]:
    """Get embeddings for text, splitting on context length overflow.

    Returns list of (text_chunk, embedding) tuples. For text that fits
    in one call, returns a single-element list. On context length error,
    recursively splits text in half (up to _MAX_SPLIT_DEPTH = 3, i.e.
    max 8 sub-chunks).

    Used for document ingestion where preserving all content is more
    important than having a single vector.
    """
    global _embedding_cache_hits, _embedding_cache_misses

    # Adaptive truncation only at top level
    if depth == 0:
        max_chars = _get_max_embedding_chars(text)
        if len(text) > max_chars:
            logger.warning(
                "embedding.truncated",
                original_chars=len(text),
                max_chars=max_chars,
                text_preview=text[:100],
            )
            text = text[:max_chars].rsplit(" ", 1)[0]

    cache_key = hash((text, model))

    with _embedding_cache_lock:
        if cache_key in _embedding_cache:
            _embedding_cache_hits += 1
            return [(text, _embedding_cache[cache_key])]

    _embedding_cache_misses += 1

    session = get_http_session()
    ollama_url = _settings.ollama_host

    logger.warning(
        "embedding.request.size",
        model=model,
        chars=len(text),
        words=len(text.split()),
        depth=depth,
        text_preview=text[:100],
    )

    try:
        embedding = _call_ollama_embedding(text, model, session, ollama_url)

        with _embedding_cache_lock:
            _embedding_cache[cache_key] = embedding

        return [(text, embedding)]

    except _ContextLengthError:
        if depth >= _MAX_SPLIT_DEPTH:
            logger.error(
                "embedding.split_max_depth",
                chars=len(text),
                depth=depth,
            )
            raise

        mid = len(text) // 2
        split_pos = text.rfind(" ", 0, mid)
        if split_pos <= 0:
            split_pos = mid

        left = text[:split_pos].strip()
        right = text[split_pos:].strip()

        logger.warning(
            "embedding.split_retry",
            depth=depth + 1,
            left_chars=len(left),
            right_chars=len(right),
        )

        left_results = get_cached_embedding_split(left, model, depth + 1)
        right_results = get_cached_embedding_split(right, model, depth + 1)
        return left_results + right_results


def get_embedding_cache_stats() -> dict:
    """Get embedding cache statistics."""
    return {
        "size": len(_embedding_cache),
        "maxsize": _embedding_cache.maxsize,
        "ttl": _embedding_cache.ttl,
        "hits": _embedding_cache_hits,
        "misses": _embedding_cache_misses,
        "hit_rate": round(
            _embedding_cache_hits / max(_embedding_cache_hits + _embedding_cache_misses, 1) * 100,
            1,
        ),
    }


def clear_embedding_cache() -> None:
    """Clear embedding cache and reset hit/miss counters."""
    global _embedding_cache_hits, _embedding_cache_misses

    with _embedding_cache_lock:
        _embedding_cache.clear()
        _embedding_cache_hits = 0
        _embedding_cache_misses = 0
        logger.debug("embedding_cache_cleared")
