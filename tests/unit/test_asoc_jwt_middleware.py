"""Unit tests for ASOC JWT middleware (MTRNIX-354, T4).

Tests: verify_asoc_jwt and asoc_auth FastAPI dependency.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.auth.asoc_jwt import (
    AsocAuthContext,
    AsocJwtExpiredError,
    AsocJwtInvalidError,
    AsocJwtMissingClaimError,
    verify_asoc_jwt,
)

_SECRET = "test-secret-1234"
_ALGO = "HS256"


def _make_token(
    user_id: str = "u1",
    project_id: str = "proj1",
    exp_offset_seconds: int = 3600,
    secret: str = _SECRET,
    algorithm: str = _ALGO,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "sub": user_id,
        "project_id": project_id,
        "exp": int(time.time()) + exp_offset_seconds,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=algorithm)


# ---------------------------------------------------------------------------
# verify_asoc_jwt
# ---------------------------------------------------------------------------


class TestVerifyAsocJwt:
    def test_valid_token_returns_context(self) -> None:
        token = _make_token()
        ctx = verify_asoc_jwt(token, _SECRET, _ALGO)

        assert isinstance(ctx, AsocAuthContext)
        assert ctx.user_id == "u1"
        assert ctx.project_id == "proj1"
        assert ctx.user_jwt == token

    def test_expired_token_raises_expired(self) -> None:
        token = _make_token(exp_offset_seconds=-1)

        with pytest.raises(AsocJwtExpiredError):
            verify_asoc_jwt(token, _SECRET, _ALGO)

    def test_wrong_secret_raises_invalid(self) -> None:
        token = _make_token(secret="other-secret")

        with pytest.raises(AsocJwtInvalidError):
            verify_asoc_jwt(token, _SECRET, _ALGO)

    def test_algorithm_pinning_rejects_none_algorithm(self) -> None:
        """Tokens encoded with 'none' algorithm must be rejected."""
        # Manually craft a token with alg=none
        import base64
        import json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=")
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(
                {"sub": "u1", "project_id": "proj1", "exp": int(time.time()) + 3600}
            ).encode()
        ).rstrip(b"=")
        none_token = f"{header.decode()}.{payload_b64.decode()}."

        with pytest.raises(AsocJwtInvalidError):
            verify_asoc_jwt(none_token, _SECRET, _ALGO)

    def test_missing_sub_raises_missing_claim(self) -> None:
        payload: dict[str, Any] = {
            "project_id": "proj1",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _SECRET, algorithm=_ALGO)

        with pytest.raises(AsocJwtMissingClaimError):
            verify_asoc_jwt(token, _SECRET, _ALGO)

    def test_missing_project_id_raises_missing_claim(self) -> None:
        payload: dict[str, Any] = {
            "sub": "u1",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, _SECRET, algorithm=_ALGO)

        with pytest.raises(AsocJwtMissingClaimError):
            verify_asoc_jwt(token, _SECRET, _ALGO)

    def test_malformed_token_raises_invalid(self) -> None:
        with pytest.raises(AsocJwtInvalidError):
            verify_asoc_jwt("not.a.jwt", _SECRET, _ALGO)

    def test_hs384_algorithm_accepted(self) -> None:
        token = _make_token(algorithm="HS384")
        ctx = verify_asoc_jwt(token, _SECRET, "HS384")
        assert ctx.user_id == "u1"

    def test_hs512_algorithm_accepted(self) -> None:
        token = _make_token(algorithm="HS512")
        ctx = verify_asoc_jwt(token, _SECRET, "HS512")
        assert ctx.user_id == "u1"

    def test_expires_at_populated_from_exp(self) -> None:
        exp_ts = int(time.time()) + 3600
        payload: dict[str, Any] = {
            "sub": "u1",
            "project_id": "proj1",
            "exp": exp_ts,
        }
        token = jwt.encode(payload, _SECRET, algorithm=_ALGO)
        ctx = verify_asoc_jwt(token, _SECRET, _ALGO)

        assert isinstance(ctx.expires_at, datetime)
        assert ctx.expires_at.tzinfo == UTC

    def test_extra_claims_in_context(self) -> None:
        token = _make_token(extra={"org_id": "org-99"})
        ctx = verify_asoc_jwt(token, _SECRET, _ALGO)
        assert ctx.claims["org_id"] == "org-99"


# ---------------------------------------------------------------------------
# asoc_auth FastAPI dependency
# ---------------------------------------------------------------------------


def _make_asoc_auth_app(secret: str = _SECRET, algorithm: str = _ALGO) -> FastAPI:
    """Helper: create a minimal FastAPI app with the asoc_auth dependency."""
    from fastapi import Depends

    from metatron.auth.asoc_jwt import asoc_auth
    from metatron.core.config import Settings

    app = FastAPI()
    settings = Settings(ASOC_SHARED_SECRET=secret, ASOC_JWT_ALGORITHM=algorithm)
    app.state.settings = settings

    @app.get("/protected")
    async def endpoint(auth: AsocAuthContext = Depends(asoc_auth)):  # noqa: B008
        return {"user_id": auth.user_id}

    return app


class TestAsocAuthDependency:
    def test_valid_bearer_returns_200(self) -> None:
        app = _make_asoc_auth_app()
        token = _make_token()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "u1"

    def test_missing_authorization_header_returns_401(self) -> None:
        app = _make_asoc_auth_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_no_secret_configured_returns_503(self) -> None:
        app = _make_asoc_auth_app(secret="")
        token = _make_token()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 503

    def test_expired_token_returns_401(self) -> None:
        app = _make_asoc_auth_app()
        expired_token = _make_token(exp_offset_seconds=-60)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/protected", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self) -> None:
        app = _make_asoc_auth_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/protected", headers={"Authorization": "Bearer garbage.token.here"}
        )
        assert resp.status_code == 401
