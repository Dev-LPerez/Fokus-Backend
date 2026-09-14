"""
Encryption utilities for sensitive OAuth tokens.

To generate a new Fernet encryption key:
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    print(key)

Save this key in your .env or production environment as TOKEN_ENCRYPTION_KEY.
"""

from cryptography.fernet import Fernet
from app.core.config import settings


def _get_fernet() -> Fernet:
    key = settings.TOKEN_ENCRYPTION_KEY
    if not key:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY no está configurada en las variables de entorno. "
            "Genera una con: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(raw: str) -> str:
    """
    Encrypts a plaintext token string using Fernet AES-128-CBC with HMAC.
    Returns the encrypted token as a string.
    """
    if not raw:
        return ""
    fernet = _get_fernet()
    return fernet.encrypt(raw.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted: str) -> str:
    """
    Decrypts an encrypted token string using Fernet.
    Returns the original plaintext token.
    """
    if not encrypted:
        return ""
    fernet = _get_fernet()
    return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
