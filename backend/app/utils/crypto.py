from __future__ import annotations

import secrets
from passlib.context import CryptContext

# use bcrypt_sha256 to avoid bcrypt's 72-byte input limit
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)

