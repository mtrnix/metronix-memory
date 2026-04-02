"""Import users from external Open WebUI instance."""

from __future__ import annotations

import secrets
import string

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from metatron.auth.openwebui_client import OpenWebUIClient

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["admin"])


def _require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", {})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _map_role_from_owui(owui_role: str) -> str:
    if owui_role == "admin":
        return "admin"
    return "viewer"


class ImportRequest(BaseModel):
    owui_url: str
    admin_email: str
    admin_password: str


@router.post("/admin/import-openwebui-users")
async def import_openwebui_users(req: ImportRequest, request: Request) -> dict:
    _require_admin(request)

    user_store = getattr(request.app.state, "user_store", None)
    api_key_store = getattr(request.app.state, "api_key_store", None)
    if not user_store or not api_key_store:
        raise HTTPException(status_code=503, detail="Stores not available")

    client = OpenWebUIClient(req.owui_url)
    try:
        await client.login(req.admin_email, req.admin_password)
    except Exception as exc:
        logger.warning("owui_import.login_failed", url=req.owui_url, error=str(exc))
        raise HTTPException(
            status_code=400, detail="Failed to login to Open WebUI. Check URL and credentials."
        ) from exc

    owui_users = await client.list_users()

    imported = []
    skipped = 0
    already_existed = 0

    for owui_user in owui_users:
        email = owui_user.get("email", "")
        name = owui_user.get("name", "")
        owui_role = owui_user.get("role", "user")

        if owui_role == "pending":
            skipped += 1
            continue

        existing = await user_store.get_user_by_email(email)
        if existing:
            already_existed += 1
            continue

        metatron_role = _map_role_from_owui(owui_role)
        password = _generate_password()

        try:
            new_user = await user_store.create_user(
                email=email,
                password=password,
                display_name=name,
                role=metatron_role,
            )
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                already_existed += 1
                continue
            raise
        raw_key = await api_key_store.create_key(user_id=new_user["id"], label="openwebui")

        imported.append(
            {
                "email": email,
                "name": name,
                "role": metatron_role,
                "metatron_password": password,
                "api_key": raw_key,
            }
        )

    logger.info(
        "owui_import.done",
        imported=len(imported),
        skipped=skipped,
        existed=already_existed,
    )
    return {
        "imported": imported,
        "skipped": skipped,
        "already_existed": already_existed,
        "total_in_owui": len(owui_users),
    }
