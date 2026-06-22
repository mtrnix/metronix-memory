import base64

from metatron_installer.secrets import generate_fernet_key, generate_password


def test_fernet_key_is_32_url_safe_bytes():
    key = generate_fernet_key()
    raw = base64.urlsafe_b64decode(key)
    assert len(raw) == 32


def test_fernet_keys_are_unique():
    assert generate_fernet_key() != generate_fernet_key()


def test_password_length_and_alphabet():
    pw = generate_password(24)
    assert len(pw) == 24
    assert pw.isalnum()


def test_passwords_are_unique():
    assert generate_password() != generate_password()
