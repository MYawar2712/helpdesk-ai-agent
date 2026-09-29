"""Tenant-scoped Customer Management APIs (Day 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dto import CustomerCreateRequest, CustomerResponse, CustomerUpdateRequest
from api.pagination import PaginatedResponse, build_paginated_response
from auth.dependencies import require_permission, verify_tenant_access
from auth.rbac import Permission
from db.models import Customer, User
from db.session import get_db

router = APIRouter(prefix="/customers", tags=["customers"])

_RequireCustomerRead = Depends(require_permission(Permission.CUSTOMER_READ.value))
_RequireCustomerCreate = Depends(require_permission(Permission.CUSTOMER_CREATE.value))
_RequireCustomerUpdate = Depends(require_permission(Permission.CUSTOMER_UPDATE.value))


@router.get(
    "",
    response_model=PaginatedResponse[CustomerResponse],
    summary="List tenant customers with optional search and pagination",
)
def list_customers(
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireCustomerRead,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, description="Search by name or email"),
) -> PaginatedResponse[CustomerResponse]:
    """List customers scoped to current_user's tenant."""
    t_id = current_user.tenant_id

    query = select(Customer).where(Customer.tenant_id == t_id)

    if search:
        pattern = f"%{search}%"
        query = query.where(
            Customer.name.ilike(pattern) | Customer.email.ilike(pattern)
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    offset = (page - 1) * page_size
    items = list(
        db.scalars(
            query.order_by(Customer.created_at.desc()).offset(offset).limit(page_size)
        ).all()
    )

    return build_paginated_response(
        items=[CustomerResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Get customer by ID",
)
def get_customer(
    customer_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireCustomerRead,
) -> CustomerResponse:
    """Get single customer with tenant isolation check."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found."
        )

    verify_tenant_access(current_user, customer.tenant_id)

    return CustomerResponse.model_validate(customer)


@router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new customer",
)
def create_customer(
    payload: CustomerCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireCustomerCreate,
) -> CustomerResponse:
    """Create a new customer scoped to current_user's tenant."""
    t_id = current_user.tenant_id

    # Guard against duplicate email within the tenant
    existing = db.scalar(
        select(Customer).where(
            Customer.tenant_id == t_id,
            Customer.email == payload.email,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A customer with this email already exists in this tenant.",
        )

    customer = Customer(
        tenant_id=t_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    return CustomerResponse.model_validate(customer)


@router.patch(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Update customer details",
)
def update_customer(
    customer_id: str,
    payload: CustomerUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireCustomerUpdate,
) -> CustomerResponse:
    """Update customer fields with tenant isolation."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found."
        )

    verify_tenant_access(current_user, customer.tenant_id)

    if payload.name is not None:
        customer.name = payload.name

    if payload.email is not None:
        # Guard against email collision within tenant
        collision = db.scalar(
            select(Customer).where(
                Customer.tenant_id == customer.tenant_id,
                Customer.email == payload.email,
                Customer.id != customer_id,
            )
        )
        if collision is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Another customer with this email already exists in this tenant."
                ),
            )
        customer.email = payload.email

    if payload.phone is not None:
        customer.phone = payload.phone

    db.commit()
    db.refresh(customer)

    return CustomerResponse.model_validate(customer)
