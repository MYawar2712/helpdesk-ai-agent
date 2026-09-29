"""User Management endpoints for Platform and Tenant Administrators."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.schemas import UserResponse
from auth.audit import log_security_event
from auth.dependencies import require_permission
from auth.rbac import Permission, Role
from core.security import hash_password
from db.models import User
from db.session import get_db

router = APIRouter(prefix="/users", tags=["users"])


class UserCreateRequest(BaseModel):
    """Admin payload for creating a new user."""

    email: EmailStr
    password: str = Field(min_length=8)
    role: str = Field(default="SUPPORT_AGENT")
    tenant_id: str | None = None


class UserUpdateRequest(BaseModel):
    """Admin payload for updating user details."""

    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None


ALLOWED_ASSIGNABLE_ROLES_FOR_TENANT_ADMIN = {
    Role.TENANT_ADMIN.value,
    Role.SUPPORT_AGENT.value,
    Role.AI_AGENT.value,
    Role.CUSTOMER.value,
}


@router.get(
    "",
    response_model=list[UserResponse],
    summary="List users within tenant (or all for platform admin)",
)
def list_users(
    current_user: Annotated[
        User, Depends(require_permission(Permission.USER_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    """Return users accessible to the current administrator."""
    stmt = select(User)
    if (current_user.role or "").upper() != Role.PLATFORM_ADMIN.value:
        stmt = stmt.where(User.tenant_id == current_user.tenant_id)

    users = db.scalars(stmt).all()
    return list(users)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user details by ID",
)
def get_user(
    user_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.USER_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Get specific user by ID with tenant isolation."""
    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    if (current_user.role or "").upper() != Role.PLATFORM_ADMIN.value:
        if target_user.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to user from another tenant is forbidden.",
            )

    return target_user


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (admin only)",
)
def create_user(
    payload: UserCreateRequest,
    current_user: Annotated[
        User, Depends(require_permission(Permission.USER_CREATE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Create a new user. Prevent role privilege escalation."""
    target_role = payload.role.upper()
    is_platform_admin = (current_user.role or "").upper() == Role.PLATFORM_ADMIN.value

    # Tenant admin cannot assign PLATFORM_ADMIN role
    if not is_platform_admin and target_role == Role.PLATFORM_ADMIN.value:
        log_security_event(
            session=db,
            action="PERMISSION_DENIED",
            resource_type="user",
            resource_id=payload.email,
            actor_user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            result="denied",
            metadata={"reason": "Attempted privilege escalation to PLATFORM_ADMIN"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot assign PLATFORM_ADMIN role.",
        )

    # Derive tenant_id from current_user unless platform_admin
    effective_tenant_id = (
        payload.tenant_id if is_platform_admin else current_user.tenant_id
    )

    new_user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=target_role,
        tenant_id=effective_tenant_id,
        is_active=True,
    )
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError as err:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from err

    log_security_event(
        session=db,
        action="USER_CREATED",
        resource_type="user",
        resource_id=new_user.id,
        actor_user_id=current_user.id,
        tenant_id=effective_tenant_id,
        metadata={"created_role": target_role, "email": new_user.email},
    )

    return new_user


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update user details/role/status",
)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    current_user: Annotated[
        User, Depends(require_permission(Permission.USER_UPDATE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Update a user's role or status. Prevents privilege escalation."""
    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    is_platform_admin = (current_user.role or "").upper() == Role.PLATFORM_ADMIN.value

    if not is_platform_admin and target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to user from another tenant is forbidden.",
        )

    if payload.role is not None:
        new_role = payload.role.upper()
        if not is_platform_admin and new_role == Role.PLATFORM_ADMIN.value:
            log_security_event(
                session=db,
                action="PERMISSION_DENIED",
                resource_type="user",
                resource_id=target_user.id,
                actor_user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                result="denied",
                metadata={"reason": "Attempted escalation to PLATFORM_ADMIN"},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot promote user to PLATFORM_ADMIN role.",
            )

        old_role = target_user.role
        target_user.role = new_role
        log_security_event(
            session=db,
            action="ROLE_CHANGED",
            resource_type="user",
            resource_id=target_user.id,
            actor_user_id=current_user.id,
            tenant_id=target_user.tenant_id,
            metadata={"old_role": old_role, "new_role": new_role},
        )

    if payload.email is not None:
        target_user.email = payload.email

    if payload.is_active is not None:
        target_user.is_active = payload.is_active

    db.commit()
    db.refresh(target_user)
    return target_user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user account",
)
def delete_user(
    user_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.USER_DELETE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Delete a user account."""
    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    is_platform_admin = (current_user.role or "").upper() == Role.PLATFORM_ADMIN.value

    if not is_platform_admin and target_user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to user from another tenant is forbidden.",
        )

    db.delete(target_user)
    db.commit()

    log_security_event(
        session=db,
        action="USER_DELETED",
        resource_type="user",
        resource_id=user_id,
        actor_user_id=current_user.id,
        tenant_id=target_user.tenant_id,
    )
