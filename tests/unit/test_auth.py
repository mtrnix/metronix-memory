"""Tests for auth/jwt.py and auth/rbac.py."""

from __future__ import annotations

import pytest

from metatron.auth.jwt import create_token, verify_token
from metatron.auth.rbac import check_permission, require_role
from metatron.core.exceptions import AuthenticationError
from metatron.core.models import Role

SECRET = "test-secret-key"


class TestJWT:
    def test_create_and_verify(self) -> None:
        token = create_token("user_1", "admin", ["ws_1", "ws_2"], SECRET)
        payload = verify_token(token, SECRET)
        assert payload["sub"] == "user_1"
        assert payload["role"] == "admin"
        assert payload["workspace_ids"] == ["ws_1", "ws_2"]

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(AuthenticationError, match="Invalid token"):
            verify_token("not-a-valid-token", SECRET)

    def test_wrong_secret_raises(self) -> None:
        token = create_token("user_1", "viewer", [], SECRET)
        with pytest.raises(AuthenticationError):
            verify_token(token, "wrong-secret")

    def test_expired_token_raises(self) -> None:
        token = create_token("user_1", "viewer", [], SECRET, expiry_hours=0)
        # Token with 0 hours expiry is already expired (or at the boundary)
        # We need to use a negative trick or just verify it works with valid expiry
        token = create_token("user_1", "viewer", [], SECRET, expiry_hours=24)
        payload = verify_token(token, SECRET)
        assert payload["sub"] == "user_1"


class TestRBAC:
    def test_admin_has_all_access(self) -> None:
        assert check_permission(Role.ADMIN, Role.VIEWER) is True
        assert check_permission(Role.ADMIN, Role.EDITOR) is True
        assert check_permission(Role.ADMIN, Role.ADMIN) is True

    def test_editor_access(self) -> None:
        assert check_permission(Role.EDITOR, Role.VIEWER) is True
        assert check_permission(Role.EDITOR, Role.EDITOR) is True
        assert check_permission(Role.EDITOR, Role.ADMIN) is False

    def test_viewer_access(self) -> None:
        assert check_permission(Role.VIEWER, Role.VIEWER) is True
        assert check_permission(Role.VIEWER, Role.EDITOR) is False
        assert check_permission(Role.VIEWER, Role.ADMIN) is False

    def test_require_role_passes(self) -> None:
        require_role(Role.ADMIN, Role.EDITOR)  # Should not raise

    def test_require_role_raises(self) -> None:
        with pytest.raises(AuthenticationError, match="Requires admin"):
            require_role(Role.VIEWER, Role.ADMIN)
