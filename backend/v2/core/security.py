"""Password hashing and session-keyed CSRF; never log arguments or results."""
import hashlib
import hmac
import re
import secrets

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.exceptions import UnknownHashError

PASSWORD_HASHER = PasswordHash((Argon2Hasher(memory_cost=65536, time_cost=3, parallelism=1),))
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 random bits, 43 base64url characters.


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(cookie_secret: str) -> str:
    # The HttpOnly, host-only random cookie is the HMAC key; it is never returned.
    # Different authentication sessions therefore have different CSRF tokens.
    return hmac.new(cookie_secret.encode(), b"ds-assistant-v2/csrf/v1", hashlib.sha256).hexdigest()


def verify_password(password: str, encoded: str | None) -> tuple[bool, str | None]:
    try:
        valid, updated = PASSWORD_HASHER.verify_and_update(password, encoded or DUMMY_HASH)
        return bool(encoded) and valid, updated
    except (UnknownHashError, ValueError):
        PASSWORD_HASHER.verify(password, DUMMY_HASH)
        return False, None
