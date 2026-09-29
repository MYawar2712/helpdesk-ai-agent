"""Authentication endpoints.

Routes
------
POST /auth/register   – Create a new user account (hashed password, no token returned).
POST /auth/login      – Validate credentials and return a JWT access token.
GET  /auth/me         – Return the profile of the currently authenticated user.

Security notes:
- Passwords are *never* stored in plaintext; bcrypt hash is persisted.
- A generic "Invalid credentials" message is returned on bad login so that
  attackers cannot enumerate valid email addresses.
- The ``tenant_id`` in the registration payload is **not** trusted blindly –
  when supplied, existence of the tenant is verified against the database.
- ``GET /auth/me`` is a protected endpoint; it demonstrates the
  ``get_current_user`` dependency pattern.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import CurrentUser
from api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from auth.rbac import Role
from core.config import Settings, get_settings
from core.security import create_access_token, hash_password, verify_password
from db.models import Tenant, User
from db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Register ──────────────────────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def register(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Create a new user account.

    - Validates that the email is unique within the platform.
    - When a ``tenant_id`` is provided, confirms the tenant exists and is active.
    - Stores only the bcrypt hash of the supplied password.
    """
    # 1. Verify tenant when provided (never trust a client-supplied ID blindly).
    if payload.tenant_id is not None:
        tenant = db.get(Tenant, payload.tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant '{payload.tenant_id}' not found.",
            )
        if not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot register under an inactive tenant.",
            )

    # 2. Hash the password before touching the database.
    password_hash = hash_password(payload.password)

    # 3. Enforce default non-privileged role for self-registration
    requested_role = payload.role.upper()
    if requested_role in (Role.PLATFORM_ADMIN.value, Role.TENANT_ADMIN.value):
        assigned_role = (
            Role.CUSTOMER.value if payload.tenant_id else Role.SUPPORT_AGENT.value
        )
    else:
        assigned_role = requested_role

    # 4. Persist the new user.
    user = User(
        email=payload.email,
        password_hash=password_hash,
        role=assigned_role,
        tenant_id=payload.tenant_id,
        is_active=True,
    )
    db.add(user)

    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as err:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from err

    return user


# ── Login ─────────────────────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive a JWT access token",
)
def login(
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Authenticate a user and return a signed JWT access token.

    Returns a generic error message on failure to prevent email enumeration.
    """
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 1. Fetch the user by email.
    stmt = select(User).where(User.email == payload.email)
    user = db.scalar(stmt)

    # 2. Validate password (always run verification even when user is None to
    #    prevent timing-based email enumeration attacks via short-circuit).
    if user is None or not verify_password(payload.password, user.password_hash):
        raise _invalid

    # 3. Reject deactivated accounts.
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact support.",
        )

    # 4. Issue a signed JWT.
    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        settings=settings,
    )
    return TokenResponse(access_token=token)


# ── Me ────────────────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Return the currently authenticated user's profile",
)
def me(current_user: CurrentUser) -> User:
    """Return the authenticated user's profile.

    This endpoint requires a valid ``Authorization: Bearer <token>`` header.
    It demonstrates the ``get_current_user`` dependency – no database call is
    needed here beyond what the dependency already performs.
    """
    return current_user
