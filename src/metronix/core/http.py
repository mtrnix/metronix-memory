"""HTTP connection pooling with retry strategy.

Provides a thread-safe singleton ``requests.Session`` with connection
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
_http_session_lock = threading.Lock()


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
                _http_session = requests.Session()

                retry = Retry(
                    total=3,
                    backoff_factor=0.5,
                    status_forcelist=[502, 503, 504],
                    allowed_methods=["GET", "POST"],
                )

                adapter = HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=retry,
                )

                _http_session.mount("http://", adapter)
                _http_session.mount("https://", adapter)

                logger.debug("http_session_initialized")

    return _http_session


def close_http_session() -> None:
    """Close the shared HTTP session (for cleanup on shutdown)."""
    global _http_session

    if _http_session is not None:
        with _http_session_lock:
            if _http_session is not None:
                _http_session.close()
                _http_session = None
                logger.debug("http_session_closed")
