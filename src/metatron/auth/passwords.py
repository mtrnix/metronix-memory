# TODO: Add unit tests (test_passwords.py) — see review C6
"""Password hashing utilities using bcrypt."""
from __future__ import annotations

import bcrypt

MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (cost factor 12)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def validate_password(password: str) -> None:
    """Raise ValueError if password doesn't meet requirements."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
