"""Tests for metronix.mcp.auth — API key validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from metronix.auth.jwt import create_token
from metronix.mcp.auth import (
    authenticate_jwt,
    get_api_key,
    require_api_key,
    validate_api_key,
)
from metronix.mcp.principal import get_current_principal


class TestGetApiKey:
    def test_returns_env_value(self) -> None:
        with patch.dict(os.environ, {"METRONIX_MCP_API_KEY": "secret"}):
            assert get_api_key() == "secret"

    def test_returns_none_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key if present
            os.environ.pop("METRONIX_MCP_API_KEY", None)
            assert get_api_key() is None


class TestValidateApiKey:
    def test_no_key_configured_allows_all(self) -> None:
        with patch("metronix.mcp.auth.get_api_key", return_value=None):
            assert validate_api_key(None) is True
            assert validate_api_key("Bearer anything") is True

    def test_missing_header_rejects(self) -> None:
        with patch("metronix.mcp.auth.get_api_key", return_value="secret"):
            assert validate_api_key(None) is False

    def test_wrong_format_rejects(self) -> None:
        with patch("metronix.mcp.auth.get_api_key", return_value="secret"):
            assert validate_api_key("Basic secret") is False

    def test_wrong_token_rejects(self) -> None:
        with patch("metronix.mcp.auth.get_api_key", return_value="secret"):
            assert validate_api_key("Bearer wrong") is False

    def test_correct_token_passes(self) -> None:
        with patch("metronix.mcp.auth.get_api_key", return_value="secret"):
            assert validate_api_key("Bearer secret") is True


class TestRequireApiKey:
    def test_raises_on_invalid(self) -> None:
        with patch("metronix.mcp.auth.get_api_key", return_value="secret"):  # noqa: SIM117
            with pytest.raises(PermissionError):
                require_api_key(None)

    def test_passes_on_valid(self) -> None:
        with patch("metronix.mcp.auth.get_api_key", return_value="secret"):
            require_api_key("Bearer secret")  # Should not raise


def test_authenticate_jwt_returns_server_derived_principal() -> None:
    token = create_token(
        user_id="user-1", role="editor", workspace_ids=["ws-a", "ws-b"], secret_key="test-secret"
    )

    principal = authenticate_jwt(f"Bearer {token}", "test-secret")

    assert principal.user_id == "user-1"
    assert principal.role == "editor"
    assert principal.workspace_ids == ("ws-a", "ws-b")
    assert principal.auth_method == "jwt"
    assert get_current_principal() is None


def test_authenticate_jwt_normalizes_empty_admin_grants() -> None:
    token = create_token(
        user_id="admin-1", role="admin", workspace_ids=[], secret_key="test-secret"
    )

    assert authenticate_jwt(f"Bearer {token}", "test-secret").workspace_ids == ("*",)


@pytest.mark.parametrize("header", [None, "Basic token", "Bearer invalid"])
def test_authenticate_jwt_rejects_invalid_bearer_credentials(header: str | None) -> None:
    with pytest.raises(PermissionError, match="Invalid or missing JWT"):
        authenticate_jwt(header, "test-secret")
