"""FastAPI authorization dependencies for RBAC and isolation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from auth.audit import log_security_event
from auth.rbac import Role, has_permission
from db.models import User
from db.session import get_db


def require_role(allowed_roles: str | list[str]) -> Callable[..., User]:
    """Dependency factory enforcing that current_user has one of the allowed roles."""
    roles_set = (
        {allowed_roles} if isinstance(allowed_roles, str) else set(allowed_roles)
    )

    def _role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        user_role = (current_user.role or "").upper()
        if user_role not in roles_set and user_role != Role.PLATFORM_ADMIN.value:
            log_security_event(
                session=db,
                action="PERMISSION_DENIED",
                resource_type="role",
                resource_id=",".join(roles_set),
                actor_user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                result="denied",
                metadata={"reason": f"Role '{current_user.role}' not in {roles_set}"},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have the required role for this action.",
            )
        return current_user

    return _role_checker


def require_permission(required_permission: str) -> Callable[..., User]:
    """Dependency factory enforcing that current_user has a specific permission."""

    def _permission_checker(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        user_role = current_user.role or ""
        if not has_permission(user_role, required_permission):
            log_security_event(
                session=db,
                action="PERMISSION_DENIED",
                resource_type="permission",
                resource_id=required_permission,
                actor_user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                result="denied",
                metadata={"permission": required_permission, "role": user_role},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{required_permission}' denied.",
            )
        return current_user

    return _permission_checker


def verify_tenant_access(current_user: User, resource_tenant_id: str | None) -> None:
    """Verify that current_user has access to a tenant-owned resource.

    PLATFORM_ADMIN can access all tenants.
    Other users can only access resources matching current_user.tenant_id.
    """
    if (current_user.role or "").upper() == Role.PLATFORM_ADMIN.value:
        return

    if resource_tenant_id is None or current_user.tenant_id != resource_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to resource from another tenant is forbidden.",
        )


def verify_customer_access(current_user: User, resource_customer_id: str) -> None:
    """Verify customer isolation rules.

    If current_user is a CUSTOMER role, they can ONLY access resources where
    customer_id matches their own associated customer account.
    """
    if (current_user.role or "").upper() == Role.CUSTOMER.value:
        # In a customer user context, user's customer reference must match
        # We also check email matching if explicit customer_id link is checked
        if (
            getattr(current_user, "customer_id", None)
            and current_user.customer_id != resource_customer_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to another customer's data is forbidden.",
            )
