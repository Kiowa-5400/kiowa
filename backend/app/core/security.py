"""Password hashing and one-time token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256

_hasher = PasswordHasher()

# Verified against when an email has no account, so a login attempt costs the
# same whether or not the account exists (no timing-based account discovery).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_new_password(password: str) -> str | None:
    """Returns a human-readable problem with ``password``, or None if acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    return None


def new_token() -> str:
    """A URL-safe random token suitable for sessions and emailed links."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Tokens are stored hashed so a database leak doesn't hand out live sessions/links."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
