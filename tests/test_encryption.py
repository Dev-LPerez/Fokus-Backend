import pytest
from cryptography.fernet import Fernet
from app.core.encryption import encrypt_token, decrypt_token
from app.core.config import settings


def test_encryption_and_decryption(monkeypatch):
    test_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", test_key)

    raw_token = "ya29.a0AfH6SMB_secret_access_token_12345"
    encrypted = encrypt_token(raw_token)

    assert encrypted != raw_token
    assert isinstance(encrypted, str)

    decrypted = decrypt_token(encrypted)
    assert decrypted == raw_token


def test_encryption_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", "")

    with pytest.raises(ValueError, match="TOKEN_ENCRYPTION_KEY no está configurada"):
        encrypt_token("some_token")
