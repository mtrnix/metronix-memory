"""Unit tests for resolve_workspace_id — query-aware workspace resolution
with a JWT access check (family-B Control Center scoping).

After the PR-127 review the resolver is strict: empty/whitespace -> auth-derived
fallback, explicit ``"*"`` -> 400, charset/length-violating input -> 400, and
absence of access -> 403. There is no fail-open branch for empty ``workspace_ids``;
admin tokens are normalised to ``["*"]`` by ``OptionalAuthMiddleware`` and by the
email-login flow before they ever reach this resolver.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from metronix.api.dependencies import resolve_workspace_id
from metronix.core.config import Settings


def _request(*, workspace_ids: list[str], query: dict[str, str] | None = None) -> Any:
    """Minimal stand-in for a FastAPI Request consumed by resolve_workspace_id."""
    settings = Settings(
        METRONIX_ENV="development",
        AUTH_ENABLED=False,
        METRONIX_SECRET_KEY="test-secret",
    )
    # SimpleNamespace allows arbitrary attribute writes — the resolver memoises
    # on ``request.state._workspace_id_cached``, so state must be writable.
    state = SimpleNamespace(user={"workspace_ids": workspace_ids})
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    return SimpleNamespace(state=state, app=app, query_params=query or {})


# ---------------------------------------------------------------------------
# Absent / whitespace param -> auth-derived fallback
# ---------------------------------------------------------------------------


def test_absent_param_falls_back_to_auth_derived() -> None:
    # workspace_ids[0] (not "*") -> returned, query ignored
    req = _request(workspace_ids=["ws-a", "ws-b"], query={})
    assert resolve_workspace_id(req) == "ws-a"


def test_absent_param_star_token_uses_default() -> None:
    req = _request(workspace_ids=["*"], query={})
    assert resolve_workspace_id(req) == req.app.state.settings.default_workspace_id


def test_whitespace_only_param_treated_as_absent() -> None:
    # ``%20%20`` survives URL decoding as "  "; strip -> empty -> auth-derived.
    req = _request(workspace_ids=["ws-a"], query={"workspace_id": "   "})
    assert resolve_workspace_id(req) == "ws-a"


# ---------------------------------------------------------------------------
# Access check
# ---------------------------------------------------------------------------


def test_star_token_grants_any_requested_workspace() -> None:
    req = _request(workspace_ids=["*"], query={"workspace_id": "ws-x"})
    assert resolve_workspace_id(req) == "ws-x"


def test_member_token_grants_listed_workspace() -> None:
    req = _request(workspace_ids=["ws-a", "ws-b"], query={"workspace_id": "ws-b"})
    assert resolve_workspace_id(req) == "ws-b"


def test_non_member_request_is_forbidden() -> None:
    req = _request(workspace_ids=["ws-a"], query={"workspace_id": "ws-x"})
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 403


def test_empty_workspace_ids_is_forbidden() -> None:
    # Strict: empty list = "confined to nothing", not "unrestricted".
    # Admin tokens are normalised to ``["*"]`` upstream — see middleware and
    # the email-login flow. If this test ever needs to flip, both upstream
    # normalisation sites have to change too.
    req = _request(workspace_ids=[], query={"workspace_id": "ws-x"})
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 403


def test_missing_user_state_is_forbidden() -> None:
    # AUTH_ENABLED=true + missing user dict (shouldn't happen with the current
    # middleware, but defence in depth): no workspace_ids -> 403, never silent.
    settings = Settings(
        METRONIX_ENV="development",
        AUTH_ENABLED=False,
        METRONIX_SECRET_KEY="test-secret",
    )
    req = SimpleNamespace(
        state=SimpleNamespace(user={}),
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        query_params={"workspace_id": "ws-x"},
    )
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 403


def test_workspace_ids_as_string_does_not_substring_match() -> None:
    # If a plugin auth backend ever returns ``workspace_ids`` as a bare string
    # (schema drift for a single-workspace tenant), ``"ws" in "ws-acme"`` would
    # otherwise be True. The resolver coerces non-list types to an empty list.
    req = _request(workspace_ids=[], query={"workspace_id": "ws"})
    req.state.user = {"workspace_ids": "ws-acme"}  # type: ignore[assignment]
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Input validation — 400s before any access check
# ---------------------------------------------------------------------------


def test_explicit_star_value_is_rejected() -> None:
    # ``"*"`` is a JWT wildcard, not a request target. Pre-fix it silently
    # downgraded to the auth-derived default; now 400 explicitly.
    req = _request(workspace_ids=["*"], query={"workspace_id": "*"})
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 400


def test_path_traversal_workspace_id_is_rejected() -> None:
    # Closes the snapshot-service path traversal: ``../../tmp`` would otherwise
    # have been concatenated into a filesystem path under the snapshot root.
    req = _request(workspace_ids=["*"], query={"workspace_id": "../../tmp"})
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 400


def test_overlong_workspace_id_is_rejected() -> None:
    req = _request(workspace_ids=["*"], query={"workspace_id": "a" * 65})
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 400


def test_invalid_charset_workspace_id_is_rejected() -> None:
    req = _request(workspace_ids=["*"], query={"workspace_id": "ws with space"})
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Memoisation
# ---------------------------------------------------------------------------


def test_result_is_memoised_on_request_state() -> None:
    # Single-source-of-truth: once resolved, subsequent calls within the same
    # request return the cached value even if query_params mutates afterwards
    # (defence against TOCTOU between router dep, DI helper, and handler).
    req = _request(workspace_ids=["*"], query={"workspace_id": "ws-x"})
    assert resolve_workspace_id(req) == "ws-x"
    req.query_params = {"workspace_id": "ws-y"}  # type: ignore[assignment]
    assert resolve_workspace_id(req) == "ws-x"
