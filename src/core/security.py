"""Password hashing and JWT token utilities.

Design decisions:
- bcrypt via the ``bcrypt`` library (passlib is incompatible with bcrypt 5.x /
  Python 3.13).
- ``python-jose[cryptography]`` for JWT generation and verification.
- Token payload carries ``sub`` (user ID), ``tenant_id``, ``role``, and ``exp``.
- Verification raises ``HTTPException(401)`` directly so callers stay clean.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt

from core.config import Settings

# ── Password helpers ──────────────────────────────────────────────────────────


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash of *plain_password*.

    The resulting string includes the salt and cost factor and is safe to store
    directly in the ``users.password_hash`` column.
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return ``True`` if *plain_password* matches *hashed_password*."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


# ── JWT helpers ───────────────────────────────────────────────────────────────

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def create_access_token(
    *,
    user_id: str,
    tenant_id: str | None,
    role: str,
    settings: Settings,
) -> str:
    """Encode a signed JWT access token.

    Args:
        user_id:   The ``User.id`` primary key (becomes the ``sub`` claim).
        tenant_id: The tenant this user belongs to, or ``None`` for super-admins.
        role:      The user's role string (e.g. ``"admin"``, ``"support_agent"``).
        settings:  Application settings carrying the signing secret and algorithm.

    Returns:
        A compact, URL-safe JWT string.
    """
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "exp": expires_at,
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode and verify a JWT access token.

    Args:
        token:    The raw JWT string from the ``Authorization: Bearer`` header.
        settings: Application settings carrying the signing secret and algorithm.

    Returns:
        The decoded payload dictionary (keys: ``sub``, ``tenant_id``, ``role``,
        ``exp``).

    Raises:
        HTTPException(401): If the token is malformed, expired, or the ``sub``
                            claim is missing.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as err:
        raise _CREDENTIALS_EXCEPTION from err

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise _CREDENTIALS_EXCEPTION

    return payload
