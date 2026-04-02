"""Sync Metatron users to Open WebUI (bundled scenario).

Uses admin@metatron.local credentials (same as core's seed admin)
to authenticate with Open WebUI. On first startup, registers
the admin account in Open WebUI via signup (first user = admin).
"""

from __future__ import annotations

from typing import Any

import structlog

from metatron.auth.openwebui_client import OpenWebUIClient

logger = structlog.get_logger(__name__)


class OpenWebUISync:
    """Handles user sync from Metatron -> Open WebUI."""

    def __init__(
        self,
        owui_url: str,
        metatron_url: str,
        admin_email: str = "admin@metatron.local",
        admin_password: str = "metatron",
    ) -> None:
        self._owui_url = owui_url
        self._metatron_url = metatron_url
        self._admin_email = admin_email
        self._admin_password = admin_password
        self._client = OpenWebUIClient(owui_url) if owui_url else None

    @property
    def enabled(self) -> bool:
        return bool(self._owui_url)

    def _map_role_to_owui(self, metatron_role: str) -> str:
        return "admin" if metatron_role == "admin" else "user"

    async def ensure_admin(self) -> None:
        """Ensure admin@metatron.local exists in Open WebUI.

        Tries signin first. If it fails, tries signup (first user = admin).
        """
        if not self.enabled:
            return
        try:
            await self._client.login(self._admin_email, self._admin_password)
            logger.info("owui_sync.admin.login_ok")
        except Exception:
            try:
                await self._client.signup(
                    name="Metatron Admin",
                    email=self._admin_email,
                    password=self._admin_password,
                )
                logger.info("owui_sync.admin.signup_ok")
            except Exception as exc:
                logger.warning("owui_sync.admin.failed", error=str(exc))

    async def _ensure_login(self) -> None:
        if self._client and not self._client.is_authenticated:
            await self.ensure_admin()

    async def sync_user_created(
        self,
        email: str,
        name: str,
        password: str,
        role: str,
        api_key: str,
    ) -> dict[str, Any] | None:
        """Create user in Open WebUI + set Direct Connection."""
        if not self.enabled:
            return None
        try:
            await self._ensure_login()
            owui_user = await self._client.create_user(
                name=name,
                email=email,
                password=password,
                role=self._map_role_to_owui(role),
            )
            owui_token = owui_user.get("token", "")
            if owui_token and self._metatron_url:
                await self._client.set_direct_connection(
                    user_token=owui_token,
                    metatron_url=self._metatron_url,
                    api_key=api_key,
                )
            logger.info("owui_sync.user_created", email=email)
            return {"owui_user_id": owui_user.get("id", ""), "owui_token": owui_token}
        except Exception as exc:
            logger.warning("owui_sync.create_failed", email=email, error=str(exc))
            return None

    async def sync_user_updated(
        self,
        owui_user_id: str,
        name: str,
        email: str,
        role: str,
        password: str | None = None,
    ) -> bool:
        """Update user in Open WebUI."""
        if not self.enabled:
            return False
        try:
            await self._ensure_login()
            await self._client.update_user(
                user_id=owui_user_id,
                name=name,
                email=email,
                role=self._map_role_to_owui(role),
                password=password,
            )
            logger.info("owui_sync.user_updated", email=email)
            return True
        except Exception as exc:
            logger.warning("owui_sync.update_failed", email=email, error=str(exc))
            return False

    async def sync_user_deleted(self, owui_user_id: str) -> bool:
        """Delete user from Open WebUI."""
        if not self.enabled:
            return False
        try:
            await self._ensure_login()
            await self._client.delete_user(owui_user_id)
            logger.info("owui_sync.user_deleted", owui_user_id=owui_user_id)
            return True
        except Exception as exc:
            logger.warning("owui_sync.delete_failed", error=str(exc))
            return False
