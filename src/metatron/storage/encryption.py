"""Fernet symmetric encryption for connector credentials.

Credentials are encrypted before storage in PostgreSQL and decrypted
only when configuring a connector. The Fernet key comes from Settings.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


def encrypt_value(plaintext: str, key: str) -> bytes:
    """Encrypt a string value using Fernet.

    Args:
        plaintext: The value to encrypt.
        key: URL-safe base64-encoded 32-byte Fernet key.

    Returns:
        Encrypted bytes (Fernet token).
    """
    f = Fernet(key.encode())
    return f.encrypt(plaintext.encode())


def decrypt_value(token: bytes, key: str) -> str:
    """Decrypt a Fernet token back to plaintext.

    Args:
        token: Encrypted bytes from encrypt_value().
        key: Same Fernet key used for encryption.

    Returns:
        Decrypted plaintext string.
    """
    f = Fernet(key.encode())
    return f.decrypt(token).decode()
