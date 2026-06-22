from __future__ import annotations

import base64
import secrets as _secrets
import string

_ALPHABET = string.ascii_letters + string.digits


def generate_fernet_key() -> str:
    """32 random bytes, url-safe base64 — the shape metatron's Fernet expects."""
    return base64.urlsafe_b64encode(_secrets.token_bytes(32)).decode()


def generate_password(length: int = 24) -> str:
    """Alphanumeric password safe to embed unquoted in .env and compose."""
    return "".join(_secrets.choice(_ALPHABET) for _ in range(length))
