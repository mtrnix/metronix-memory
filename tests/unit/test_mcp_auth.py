"""Tests for metronix.mcp.auth — API key validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from metronix.mcp.auth import get_api_key, require_api_key, validate_api_key


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
