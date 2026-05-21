"""Unit tests for ASOC-specific CORS middleware (MTRNIX-370, Item C).

Tests cover:
- CORS disabled by default when asoc_allowed_origins is empty.
- CORS enabled when origins are configured (OPTIONS preflight).
- allow_credentials=True present when origins configured.

Uses a bare FastAPI app with only the CORS middleware wired (no lifespan) so
the test does not depend on external services (DB, MCP session manager, etc.).
The middleware registration logic under test lives in create_app() but is
replicated here at minimum fidelity to keep tests isolated and fast.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from metatron.core.config import Settings


def _make_settings(asoc_allowed_origins: list[str] | None = None) -> Settings:
    """Construct a minimal Settings with defaults safe for unit tests."""
    kwargs: dict[str, object] = {}
    if asoc_allowed_origins is not None:
        kwargs["asoc_allowed_origins"] = asoc_allowed_origins
    return Settings.model_construct(**kwargs)


def _make_app(settings: Settings) -> FastAPI:
    """Build a minimal FastAPI app with only the ASOC CORS middleware wired.

    Replicates the CORS block from create_app() without the full lifespan so
    tests can run without DB or MCP session manager.
    """
    app = FastAPI()

    # Generic CORS (mirrors create_app) — wildcard, no credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ASOC-specific CORS — the conditional block we are testing.
    if settings.asoc_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.asoc_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-ASOC-Session"],
        )

    # Add a dummy route so the app has something to route to.
    @app.get("/api/v1/asoc/chat")
    async def _stub() -> dict[str, str]:
        return {"ok": "true"}

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _options_preflight(
    client: TestClient,
    origin: str,
    path: str = "/api/v1/asoc/chat",
) -> object:
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cors_disabled_when_origins_empty() -> None:
    """Default settings (no ASOC origins) → no ASOC CORS headers on preflight."""
    settings = _make_settings()
    # asoc_allowed_origins defaults to []
    assert settings.asoc_allowed_origins == []

    with TestClient(_make_app(settings), raise_server_exceptions=False) as client:
        resp = _options_preflight(client, "https://asoc.example.com")
        # No ASOC-specific ACAO header — the generic CORS middleware may or may
        # not respond with "*"; we only assert the ASOC origin is NOT reflected.
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao != "https://asoc.example.com"


def test_cors_enabled_when_origins_configured() -> None:
    """When asoc_allowed_origins is set, OPTIONS preflight reflects the origin."""
    settings = _make_settings(asoc_allowed_origins=["https://asoc.example.com"])
    assert settings.asoc_allowed_origins == ["https://asoc.example.com"]

    with TestClient(_make_app(settings), raise_server_exceptions=False) as client:
        resp = _options_preflight(client, "https://asoc.example.com")
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == "https://asoc.example.com"


def test_cors_credentials_supported() -> None:
    """Access-Control-Allow-Credentials: true when origins are configured."""
    settings = _make_settings(asoc_allowed_origins=["https://asoc.example.com"])

    with TestClient(_make_app(settings), raise_server_exceptions=False) as client:
        resp = _options_preflight(client, "https://asoc.example.com")
        acac = resp.headers.get("access-control-allow-credentials", "")
        assert acac.lower() == "true"
