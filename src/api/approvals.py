"""Human review queue APIs (Day 9).

Every endpoint derives the tenant from the authenticated user; ``tenant_id`` is
never taken from the request body or a path segment. A tenant admin or support
agent can only ever see and decide approvals belonging to their own tenant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.actions import ApprovalStatus
from auth.dependencies import require_permission, verify_tenant_access
from auth.rbac import Permission
from db.models import ApprovalRequest, Conversation, Message, User
from db.session import get_db
from hitl.service import (
    ApprovalConflict,
    ApprovalError,
    ApprovalExpired,
    ApprovalNotFound,
    ApprovalService,
)

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalResponse(BaseModel):
    """Serialized approval request."""

    id: str
    tenant_id: str
    conversation_id: str
    ticket_id: str | None = None
    requested_by: str
    agent_type: str
    action_type: str
    resource_type: str
    resource_id: str | None = None
    reason: str | None = None
    risk_level: str
    status: str
    reviewed_by: str | None = None
    review_comment: str | None = None
    expires_at: str | None = None
    created_at: str | None = None

    @classmethod
    def from_model(cls, row: ApprovalRequest) -> ApprovalResponse:
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            conversation_id=row.conversation_id,
            ticket_id=row.ticket_id,
            requested_by=row.requested_by,
            agent_type=row.agent_type,
            action_type=row.action_type,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            reason=row.reason,
            risk_level=row.risk_level,
            status=row.status,
            reviewed_by=row.reviewed_by,
            review_comment=row.review_comment,
            expires_at=row.expires_at.isoformat() if row.expires_at else None,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )


class ReviewRequest(BaseModel):
    """Reviewer comment. The decision itself comes from the endpoint used."""

    comment: str | None = Field(default=None, max_length=2000)


def _tenant_id(current_user: User) -> str:
    """Return the authenticated tenant, rejecting users without one."""

    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a tenant.",
        )
    return current_user.tenant_id


def _service(db: Session, current_user: User) -> ApprovalService:
    return ApprovalService(db)


def _handle(error: Exception) -> HTTPException:
    """Map a workflow error onto an appropriate HTTP response."""

    if isinstance(error, ApprovalNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found."
        )
    if isinstance(error, ApprovalExpired):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This approval request has expired.",
        )
    if isinstance(error, ApprovalConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Approval request failed."
    )


@router.get("", response_model=list[ApprovalResponse], summary="List approvals")
def list_approvals(
    current_user: Annotated[
        User, Depends(require_permission(Permission.APPROVAL_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    agent_type: str | None = None,
    limit: int = 50,
) -> list[ApprovalResponse]:
    """Return the tenant's review queue, newest first."""

    rows = _service(db, current_user).list(
        tenant_id=_tenant_id(current_user),
        status=status_filter,
        agent_type=agent_type,
        limit=limit,
    )
    return [ApprovalResponse.from_model(row) for row in rows]


@router.get(
    "/{approval_id}", response_model=ApprovalResponse, summary="Get one approval"
)
def get_approval(
    approval_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.APPROVAL_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalResponse:
    """Return one approval, enforcing tenant isolation."""

    try:
        row = _service(db, current_user).get(
            approval_id, tenant_id=_tenant_id(current_user)
        )
    except ApprovalError as error:
        raise _handle(error) from error
    verify_tenant_access(current_user, row.tenant_id)
    return ApprovalResponse.from_model(row)


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalResponse,
    summary="Approve a pending action",
)
def approve(
    approval_id: str,
    request: Request,
    current_user: Annotated[
        User, Depends(require_permission(Permission.APPROVAL_DECIDE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
    payload: ReviewRequest | None = None,
) -> ApprovalResponse:
    """Approve a request. The action itself is executed on graph resume."""

    service = _service(db, current_user)
    tenant_id = _tenant_id(current_user)
    try:
        row = service.get(approval_id, tenant_id=tenant_id)
        verify_tenant_access(current_user, row.tenant_id)
        row = service.approve(
            approval_id, tenant_id=tenant_id, reviewer_id=current_user.id
        )
        if payload is not None and payload.comment:
            row.review_comment = payload.comment[:2000]
            db.commit()
            db.refresh(row)
        # Approving changes the database status, but the job is created only
        # when the paused LangGraph thread is resumed with the same identity.
        conversation = db.get(Conversation, row.conversation_id)
        agent = getattr(request.app.state, "agent", None)
        if conversation is None or agent is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The paused agent workflow is unavailable.",
            )
        resumed = agent.resume(
            conversation_id=conversation.id,
            customer_id=conversation.customer_id,
            tenant_id=tenant_id,
            decision={"approval_id": row.id, "decision": "approved"},
        )
        # The approval service persists the authoritative tool result. Read it
        # back after resume; checkpoint state can contain a job_id from an
        # earlier conversation turn.
        db.refresh(row)
        # Prefer the ID returned by this approved execution. The checkpoint
        # may contain an older top-level job_id from an earlier turn.
        result = resumed.get("agent_result") or {}
        data = result.get("data") or {}
        execution = row.execution_result or {}
        job_id = (
            (execution.get("job") or {}).get("id")
            or data.get("job_id")
            or (data.get("payload") or {}).get("job", {}).get("id")
        )
        parameters = (row.payload or {}).get("parameters") or {}
        scheduled_at = parameters.get("scheduled_at")
        schedule_text = ""
        if scheduled_at:
            from utils.date_parser import (
                format_schedule_datetime,
                parse_natural_datetime,
            )

            parsed_schedule = parse_natural_datetime(str(scheduled_at))
            if parsed_schedule:
                schedule_text = f" for {format_schedule_datetime(parsed_schedule)}"
        confirmation = (
            f"Great news! Your service visit{schedule_text} has been successfully "
            f"scheduled{f'. Reference Job ID: {job_id}' if job_id else '.'}"
        )
        db.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                sender_type="AI",
                content=confirmation,
            )
        )
        conversation.updated_at = datetime.now(UTC)
        db.commit()
    except ApprovalError as error:
        raise _handle(error) from error
    return ApprovalResponse.from_model(row)


@router.post(
    "/{approval_id}/reject",
    response_model=ApprovalResponse,
    summary="Reject a pending action",
)
def reject(
    approval_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.APPROVAL_DECIDE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
    payload: ReviewRequest | None = None,
) -> ApprovalResponse:
    """Reject a request. The action is not executed."""

    service = _service(db, current_user)
    tenant_id = _tenant_id(current_user)
    try:
        row = service.get(approval_id, tenant_id=tenant_id)
        verify_tenant_access(current_user, row.tenant_id)
        row = service.reject(
            approval_id,
            tenant_id=tenant_id,
            reviewer_id=current_user.id,
            comment=payload.comment if payload else None,
        )
    except ApprovalError as error:
        raise _handle(error) from error
    return ApprovalResponse.from_model(row)


@router.post(
    "/{approval_id}/cancel",
    response_model=ApprovalResponse,
    summary="Cancel a pending request",
)
def cancel(
    approval_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.APPROVAL_DECIDE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalResponse:
    """Cancel a still-pending request."""

    service = _service(db, current_user)
    tenant_id = _tenant_id(current_user)
    try:
        row = service.cancel(approval_id, tenant_id=tenant_id, actor_id=current_user.id)
    except ApprovalError as error:
        raise _handle(error) from error
    return ApprovalResponse.from_model(row)


@router.get("/{approval_id}/status", summary="Approval status for the customer surface")
def approval_status(
    approval_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.APPROVAL_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Return a minimal, non-sensitive status view of an approval."""

    try:
        row = _service(db, current_user).get(
            approval_id, tenant_id=_tenant_id(current_user)
        )
    except ApprovalError as error:
        raise _handle(error) from error
    return {
        "id": row.id,
        "status": row.status,
        "action_type": row.action_type,
        # The customer never sees payloads, reviewer identity, or risk internals.
        "requires_human": row.status == ApprovalStatus.PENDING.value,
    }
