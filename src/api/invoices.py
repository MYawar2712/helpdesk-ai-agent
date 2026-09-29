"""Tenant-scoped Invoice Management APIs (Day 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dto import InvoiceCreateDTO, InvoiceResponse, InvoiceUpdateDTO
from api.pagination import PaginatedResponse, build_paginated_response
from auth.dependencies import (
    require_permission,
    verify_customer_access,
    verify_tenant_access,
)
from auth.rbac import Permission
from db.models import Customer, Invoice, Job, User
from db.session import get_db

router = APIRouter(prefix="/invoices", tags=["invoices"])

_RequireInvoiceRead = Depends(require_permission(Permission.INVOICE_READ.value))
_RequireInvoiceCreate = Depends(require_permission(Permission.INVOICE_CREATE.value))
_RequireInvoiceUpdate = Depends(require_permission(Permission.INVOICE_UPDATE.value))

VALID_INVOICE_STATUSES = {"unpaid", "paid", "overdue", "cancelled"}


@router.get(
    "",
    response_model=PaginatedResponse[InvoiceResponse],
    summary="List tenant invoices with optional filtering and pagination",
)
def list_invoices(
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireInvoiceRead,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: str | None = Query(default=None),
    job_id: str | None = Query(default=None),
) -> PaginatedResponse[InvoiceResponse]:
    """List invoices scoped to current_user's tenant."""
    t_id = current_user.tenant_id

    # Enforce customer isolation for CUSTOMER-role users
    verify_customer_access(
        current_user, customer_id or getattr(current_user, "customer_id", "")
    )

    query = select(Invoice).where(Invoice.tenant_id == t_id)

    if status_filter:
        query = query.where(Invoice.status == status_filter)
    if customer_id:
        query = query.where(Invoice.customer_id == customer_id)
    if job_id:
        query = query.where(Invoice.job_id == job_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    offset = (page - 1) * page_size
    items = list(
        db.scalars(
            query.order_by(Invoice.created_at.desc()).offset(offset).limit(page_size)
        ).all()
    )

    return build_paginated_response(
        items=[InvoiceResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Get invoice by ID",
)
def get_invoice(
    invoice_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireInvoiceRead,
) -> InvoiceResponse:
    """Get single invoice with tenant and customer isolation checks."""
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found."
        )

    verify_tenant_access(current_user, invoice.tenant_id)
    verify_customer_access(current_user, invoice.customer_id)

    return InvoiceResponse.model_validate(invoice)


@router.post(
    "",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new invoice for a job",
)
def create_invoice(
    payload: InvoiceCreateDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireInvoiceCreate,
) -> InvoiceResponse:
    """Create invoice validating customer and job tenant boundaries."""
    t_id = current_user.tenant_id

    # Verify customer belongs to tenant
    customer = db.get(Customer, payload.customer_id)
    if customer is None or customer.tenant_id != t_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer not found in current tenant.",
        )

    verify_customer_access(current_user, payload.customer_id)

    # Verify job belongs to tenant and matches customer
    job = db.get(Job, payload.job_id)
    if job is None or job.tenant_id != t_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job not found in current tenant.",
        )
    if job.customer_id != payload.customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job does not belong to the specified customer.",
        )

    invoice = Invoice(
        tenant_id=t_id,
        customer_id=payload.customer_id,
        job_id=payload.job_id,
        amount=payload.amount,
        status="unpaid",
        due_date=payload.due_date,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    return InvoiceResponse.model_validate(invoice)


@router.patch(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Update invoice amount, status, or due date",
)
def update_invoice(
    invoice_id: str,
    payload: InvoiceUpdateDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireInvoiceUpdate,
) -> InvoiceResponse:
    """Update invoice fields with tenant isolation."""
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found."
        )

    verify_tenant_access(current_user, invoice.tenant_id)
    verify_customer_access(current_user, invoice.customer_id)

    if payload.amount is not None:
        invoice.amount = payload.amount

    if payload.status is not None:
        if payload.status not in VALID_INVOICE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Invalid invoice status. Must be one of: "
                    f"{sorted(VALID_INVOICE_STATUSES)}"
                ),
            )
        invoice.status = payload.status

    if payload.due_date is not None:
        invoice.due_date = payload.due_date

    db.commit()
    db.refresh(invoice)

    return InvoiceResponse.model_validate(invoice)
