"""HTTP client for Open WebUI user management API."""
from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_TIMEOUT = httpx.Timeout(30.0)


class OpenWebUIClient:
    """Async client for Open WebUI REST API.

    Reuses a single httpx.AsyncClient for connection pooling.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._admin_token: str | None = None
        self._http = httpx.AsyncClient(timeout=_TIMEOUT)

    @property
    def is_authenticated(self) -> bool:
        return self._admin_token is not None

    def _headers(self, token: str | None = None) -> dict[str, str]:
        t = token or self._admin_token
        h = {"Content-Type": "application/json"}
        if t:
            h["Authorization"] = f"Bearer {t}"
        return h

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """Sign in as admin, store JWT for subsequent calls."""
        resp = await self._http.post(
            f"{self.base_url}/api/v1/auths/signin",
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._admin_token = data.get("token")
        logger.info("owui.login.ok", email=email)
        return data

    async def signup(self, name: str, email: str, password: str) -> dict[str, Any]:
        """Sign up (first user becomes admin)."""
        resp = await self._http.post(
            f"{self.base_url}/api/v1/auths/signup",
            json={"name": name, "email": email, "password": password},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._admin_token = data.get("token")
        logger.info("owui.signup.ok", email=email)
        return data

    async def list_users(self) -> list[dict[str, Any]]:
        """List all users (admin only)."""
        resp = await self._http.get(
            f"{self.base_url}/api/v1/users/",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("users", data) if isinstance(data, dict) else data

    async def create_user(
        self, name: str, email: str, password: str, role: str = "user"
    ) -> dict[str, Any]:
        """Create a user (admin only). Returns user dict with JWT token."""
        resp = await self._http.post(
            f"{self.base_url}/api/v1/auths/add",
            json={"name": name, "email": email, "password": password, "role": role},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def update_user(
        self, user_id: str, name: str, email: str, role: str,
        profile_image_url: str = "/user.png",
        password: str | None = None,
    ) -> dict[str, Any]:
        """Update a user (admin only). All fields required by OWUI API."""
        body: dict[str, Any] = {
            "name": name, "email": email, "role": role,
            "profile_image_url": profile_image_url,
        }
        if password:
            body["password"] = password
        resp = await self._http.post(
            f"{self.base_url}/api/v1/users/{user_id}/update",
            json=body,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_user(self, user_id: str) -> bool:
        """Delete a user (admin only)."""
        resp = await self._http.delete(
            f"{self.base_url}/api/v1/users/{user_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return True

    async def set_direct_connection(
        self, user_token: str, metatron_url: str, api_key: str
    ) -> None:
        """Set Direct Connection settings for a user (needs user's own JWT)."""
        body = {
            "ui": {
                "directConnections": {
                    "OPENAI_API_BASE_URLS": [metatron_url],
                    "OPENAI_API_KEYS": [api_key],
                    "OPENAI_API_CONFIGS": {
                        "0": {
                            "enable": True,
                            "tags": [],
                            "prefix_id": "",
                            "model_ids": [],
                            "connection_type": "external",
                            "auth_type": "bearer",
                        }
                    },
                }
            }
        }
        resp = await self._http.post(
            f"{self.base_url}/api/v1/users/user/settings/update",
            json=body,
            headers=self._headers(token=user_token),
        )
        resp.raise_for_status()
        logger.info("owui.direct_connection.set", metatron_url=metatron_url)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
