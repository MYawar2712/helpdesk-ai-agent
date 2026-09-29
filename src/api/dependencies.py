"""FastAPI dependency: extract and validate the current authenticated user.

Usage in a protected route::

    from api.dependencies import CurrentUser

    @router.get("/me")
    def me(user: CurrentUser) -> dict:
        return {"id": user.id, "email": user.email}

The dependency reads the ``Authorization: Bearer <token>`` header, decodes the
JWT, and fetches the live ``User`` record from the database.  It raises
``HTTP 401`` if the token is missing, invalid, or the user no longer exists.
It raises ``HTTP 403`` if the user's account has been deactivated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.security import decode_access_token
from db.models import User
from db.session import get_db

_bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """Extract, validate, and return the authenticated user.

    Steps:
    1. Parse the ``Authorization: Bearer`` header (HTTPBearer handles this).
    2. Decode and verify the JWT signature and expiry.
    3. Load the user from the database by the ``sub`` claim (user ID).
    4. Verify the user is still active.

    Returns:
        The live SQLAlchemy ``User`` ORM instance.

    Raises:
        HTTPException(401): Token missing, invalid, or user not found.
        HTTPException(403): User account is deactivated.
    """
    payload = decode_access_token(credentials.credentials, settings)
    user_id: str = payload["sub"]

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    return user


# Convenient type alias for dependency injection in route signatures.
CurrentUser = Annotated[User, Depends(get_current_user)]
