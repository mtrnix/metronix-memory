"""HTTP connection pooling with retry strategy.

Provides thread-safe singleton ``requests.Session`` objects with connection
pooling and automatic retries for transient server errors.
"""
# TODO: migrate to httpx.AsyncClient

from __future__ import annotations

import threading

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = structlog.get_logger()

_http_session: requests.Session | None = None
_generation_session: requests.Session | None = None
_http_session_lock = threading.Lock()


def _build_session(*, retry_reads: bool) -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "POST"],
        # False raises a read timeout at once instead of sending the request again.
        read=None if retry_reads else False,
    )

    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=20,
        max_retries=retry,
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get_http_session() -> requests.Session:
    """Get shared HTTP session with connection pooling.

    Features:
        - Connection pooling (10 connections, 20 max per host)
        - Automatic retries (3 attempts with exponential backoff)
        - Thread-safe singleton
    """
    global _http_session

    if _http_session is None:
        with _http_session_lock:
            if _http_session is None:
                _http_session = _build_session(retry_reads=True)
                logger.debug("http_session_initialized")

    return _http_session


def get_generation_session() -> requests.Session:
    """Get the shared HTTP session for LLM generation requests.

    Same pooling and connect/5xx retries as :func:`get_http_session`, but a read
    timeout is raised instead of retried: the request already reached the model,
    and sending it again restarts a generation that just ran for the whole
    timeout (on a CPU host, minutes per attempt).
    """
    global _generation_session

    if _generation_session is None:
        with _http_session_lock:
            if _generation_session is None:
                _generation_session = _build_session(retry_reads=False)
                logger.debug("generation_session_initialized")

    return _generation_session


def close_http_session() -> None:
    """Close the shared HTTP sessions (for cleanup on shutdown)."""
    global _http_session, _generation_session

    with _http_session_lock:
        if _http_session is not None:
            _http_session.close()
            _http_session = None
            logger.debug("http_session_closed")
        if _generation_session is not None:
            _generation_session.close()
            _generation_session = None
            logger.debug("generation_session_closed")
