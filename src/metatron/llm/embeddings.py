"""Embedding cache backed by Ollama API.

Caches dense embeddings in a TTL cache to avoid redundant API calls
during high-volume operations (e.g., mass document indexing).

Thread-safe with lock protection on cache reads and writes.
"""
# TODO: migrate to use LLMProviderInterface.embed()

from __future__ import annotations

import re
import time
import threading

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

# Shrink factors for adaptive retry on context length overflow.
_SHRINK_FACTORS = (1.0, 0.7, 0.5)


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


def get_cached_embedding(
    text: str, model: str = "nomic-embed-text:latest"
) -> list[float]:
    """Get dense embedding with caching.

    Uses TTL cache to avoid redundant Ollama API calls for repeated text.
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

    # Safety truncation: prevent context overflow for embedding model
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

    word_count = len(text.split())
    logger.warning(
        "embedding.request.size",
        model=model,
        chars=len(text),
        words=word_count,
        text_preview=text[:100],
    )
    logger.debug(
        "embedding.request",
        model=model,
        text_len=len(text),
        text_preview=text[:100],
        ollama_url=ollama_url,
    )

    # Outer loop: shrink text on context length overflow (up to 3 sizes).
    # Inner loop: retry on transient errors (network, timeout) up to 3 times.
    prompt_text = text
    embedding = None

    for shrink_idx, factor in enumerate(_SHRINK_FACTORS):
        if shrink_idx > 0:
            new_len = int(len(text) * factor)
            prompt_text = text[:new_len].rsplit(" ", 1)[0]
            logger.warning(
                "embedding.shrink_retry",
                attempt=shrink_idx + 1,
                factor=factor,
                new_chars=len(prompt_text),
            )

        for attempt in range(3):
            try:
                resp = session.post(
                    f"{ollama_url}/api/embeddings",
                    json={
                        "model": model,
                        "prompt": prompt_text,
                        "options": {"num_ctx": 8192},
                    },
                    timeout=30,
                )

                # Context length error → break inner retry, try shrunk text
                if _is_context_length_error(resp):
                    logger.error(
                        "embedding.context_length",
                        status=resp.status_code,
                        body=resp.text[:200],
                        chars=len(prompt_text),
                        model=model,
                    )
                    break

                if resp.status_code >= 500:
                    logger.error(
                        "embedding.ollama_error",
                        status=resp.status_code,
                        body=resp.text,
                        model=model,
                    )
                resp.raise_for_status()
                embedding = resp.json()["embedding"]
                break
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

        if embedding is not None:
            break
    else:
        raise RuntimeError(
            f"Embedding failed: text ({len(text)} chars) exceeds context "
            f"length after {len(_SHRINK_FACTORS)} shrink attempts"
        )

    with _embedding_cache_lock:
        _embedding_cache[cache_key] = embedding

    return embedding


def get_embedding_cache_stats() -> dict:
    """Get embedding cache statistics."""
    return {
        "size": len(_embedding_cache),
        "maxsize": _embedding_cache.maxsize,
        "ttl": _embedding_cache.ttl,
        "hits": _embedding_cache_hits,
        "misses": _embedding_cache_misses,
        "hit_rate": round(
            _embedding_cache_hits
            / max(_embedding_cache_hits + _embedding_cache_misses, 1)
            * 100,
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
