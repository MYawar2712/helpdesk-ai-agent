"""Tenant-scoped Ticket Management APIs (Day 4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dto import TicketCreateDTO, TicketResponse, TicketUpdateDTO
from api.pagination import PaginatedResponse, build_paginated_response
from auth.dependencies import (
    require_permission,
    verify_customer_access,
    verify_tenant_access,
)
from auth.rbac import Permission
from db.models import Customer, Job, Ticket, User
from db.session import get_db

router = APIRouter(prefix="/tickets", tags=["tickets"])

_RequireTicketRead = Depends(require_permission(Permission.TICKET_READ.value))
_RequireTicketCreate = Depends(require_permission(Permission.TICKET_CREATE.value))
_RequireTicketUpdate = Depends(require_permission(Permission.TICKET_UPDATE.value))


@router.get(
    "",
    response_model=PaginatedResponse[TicketResponse],
    summary="List tenant support tickets with filtering and pagination",
)
def list_tickets(
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireTicketRead,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    priority_filter: str | None = Query(default=None, alias="priority"),
    intent_filter: str | None = Query(default=None, alias="intent"),
    assigned_to: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
) -> PaginatedResponse[TicketResponse]:
    """List tickets belonging to current_user's tenant."""
    t_id = current_user.tenant_id

    # Enforce customer isolation if user is a CUSTOMER
    verify_customer_access(
        current_user, customer_id or getattr(current_user, "customer_id", "")
    )

    query = select(Ticket).where(Ticket.tenant_id == t_id)

    if status_filter:
        query = query.where(Ticket.status == status_filter)
    if priority_filter:
        query = query.where(Ticket.priority == priority_filter)
    if intent_filter:
        query = query.where(Ticket.intent == intent_filter)
    if assigned_to:
        query = query.where(Ticket.handled_by == assigned_to)
    if customer_id:
        query = query.where(Ticket.customer_id == customer_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    offset = (page - 1) * page_size
    items = list(db.scalars(query.offset(offset).limit(page_size)).all())

    return build_paginated_response(
        items=[TicketResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Get support ticket by ID",
)
def get_ticket(
    ticket_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireTicketRead,
) -> TicketResponse:
    """Get single ticket with tenant and customer isolation checks."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
        )

    verify_tenant_access(current_user, ticket.tenant_id)
    verify_customer_access(current_user, ticket.customer_id)

    return TicketResponse.model_validate(ticket)


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new support ticket",
)
def create_ticket(
    payload: TicketCreateDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireTicketCreate,
) -> TicketResponse:
    """Create a new ticket scoped to current_user's tenant."""
    t_id = current_user.tenant_id

    # Verify customer belongs to tenant
    customer = db.get(Customer, payload.customer_id)
    if customer is None or customer.tenant_id != t_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer not found in current tenant.",
        )

    verify_customer_access(current_user, payload.customer_id)

    # Verify related_job_id belongs to tenant if provided
    if payload.related_job_id:
        job = db.get(Job, payload.related_job_id)
        if job is None or job.tenant_id != t_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Related job not found in current tenant.",
            )

    ticket = Ticket(
        tenant_id=t_id,
        customer_id=payload.customer_id,
        related_job_id=payload.related_job_id,
        intent=payload.intent,
        priority=payload.priority,
        status="open",
        handled_by="PENDING",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return TicketResponse.model_validate(ticket)


@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Update ticket status or priority",
)
def update_ticket(
    ticket_id: str,
    payload: TicketUpdateDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireTicketUpdate,
) -> TicketResponse:
    """Update ticket fields with tenant isolation."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
        )

    verify_tenant_access(current_user, ticket.tenant_id)
    verify_customer_access(current_user, ticket.customer_id)

    if payload.status is not None:
        ticket.status = payload.status
        if payload.status in ("closed", "resolved"):
            ticket.closed_at = datetime.now(UTC)

    if payload.priority is not None:
        ticket.priority = payload.priority

    if payload.handled_by is not None:
        ticket.handled_by = payload.handled_by

    if payload.resolution is not None:
        ticket.resolution = payload.resolution

    db.commit()
    db.refresh(ticket)

    return TicketResponse.model_validate(ticket)
