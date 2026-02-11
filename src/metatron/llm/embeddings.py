"""Embedding cache backed by Ollama API.

Caches dense embeddings in a TTL cache to avoid redundant API calls
during high-volume operations (e.g., mass document indexing).

Thread-safe with lock protection on cache reads and writes.
"""
# TODO: migrate to use LLMProviderInterface.embed()

from __future__ import annotations

import time
import threading

import structlog
from cachetools import TTLCache

from metatron.core.config import Settings
from metatron.core.http import get_http_session

logger = structlog.get_logger()

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

    session = get_http_session()
    ollama_url = _settings.ollama_host

    for attempt in range(3):
        try:
            resp = session.post(
                f"{ollama_url}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=30,
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
