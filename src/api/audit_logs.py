"""Read-only audit log API (Day 9).

Audit records are append-only: this router exposes no create, update, or delete
endpoint. Results are always restricted to the authenticated user's tenant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.dependencies import require_permission
from auth.rbac import Permission
from db.models import AuditLog, User
from db.session import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


class AuditLogResponse(BaseModel):
    """Serialized audit entry. Metadata is already sanitised on write."""

    id: str
    tenant_id: str | None = None
    actor_user_id: str | None = None
    action: str
    resource_type: str
    resource_id: str
    result: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None

    @classmethod
    def from_model(cls, row: AuditLog) -> AuditLogResponse:
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            actor_user_id=row.actor_user_id,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            result=row.result,
            metadata=row.metadata_json or None,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )


@router.get("", response_model=list[AuditLogResponse], summary="List audit logs")
def list_audit_logs(
    current_user: Annotated[
        User, Depends(require_permission(Permission.AUDIT_LOG_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_user_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditLogResponse]:
    """Return audit entries for the current tenant with optional filters."""

    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a tenant.",
        )

    stmt = select(AuditLog).where(AuditLog.tenant_id == current_user.tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)

    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [AuditLogResponse.from_model(row) for row in rows]
