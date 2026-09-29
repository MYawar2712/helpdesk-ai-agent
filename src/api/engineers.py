"""Tenant-scoped Engineer Management APIs (Day 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dto import EngineerCreateRequest, EngineerResponse, EngineerUpdateRequest
from api.pagination import PaginatedResponse, build_paginated_response
from auth.dependencies import require_permission, verify_tenant_access
from auth.rbac import Permission
from db.models import Engineer, User
from db.session import get_db

router = APIRouter(prefix="/engineers", tags=["engineers"])

_RequireEngineerRead = Depends(require_permission(Permission.ENGINEER_READ.value))
_RequireEngineerCreate = Depends(require_permission(Permission.ENGINEER_CREATE.value))
_RequireEngineerUpdate = Depends(require_permission(Permission.ENGINEER_UPDATE.value))

VALID_AVAILABILITY_STATUSES = {"available", "busy", "on_leave", "offline"}


@router.get(
    "",
    response_model=PaginatedResponse[EngineerResponse],
    summary="List tenant engineers with optional filtering and pagination",
)
def list_engineers(
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireEngineerRead,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    availability_status: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, description="Search by name or email"),
) -> PaginatedResponse[EngineerResponse]:
    """List engineers scoped to current_user's tenant."""
    t_id = current_user.tenant_id

    query = select(Engineer).where(Engineer.tenant_id == t_id)

    if availability_status:
        query = query.where(Engineer.availability_status == availability_status)

    if search:
        pattern = f"%{search}%"
        query = query.where(
            Engineer.name.ilike(pattern) | Engineer.email.ilike(pattern)
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    offset = (page - 1) * page_size
    items = list(
        db.scalars(
            query.order_by(Engineer.created_at.desc()).offset(offset).limit(page_size)
        ).all()
    )

    return build_paginated_response(
        items=[EngineerResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{engineer_id}",
    response_model=EngineerResponse,
    summary="Get engineer by ID",
)
def get_engineer(
    engineer_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireEngineerRead,
) -> EngineerResponse:
    """Get single engineer with tenant isolation check."""
    engineer = db.get(Engineer, engineer_id)
    if engineer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Engineer not found."
        )

    verify_tenant_access(current_user, engineer.tenant_id)

    return EngineerResponse.model_validate(engineer)


@router.post(
    "",
    response_model=EngineerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new engineer",
)
def create_engineer(
    payload: EngineerCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireEngineerCreate,
) -> EngineerResponse:
    """Create an engineer scoped to current_user's tenant."""
    t_id = current_user.tenant_id

    if payload.availability_status not in VALID_AVAILABILITY_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Invalid availability_status. Must be one of: "
                f"{sorted(VALID_AVAILABILITY_STATUSES)}"
            ),
        )

    # Guard against duplicate email within the tenant
    existing = db.scalar(
        select(Engineer).where(
            Engineer.tenant_id == t_id,
            Engineer.email == payload.email,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An engineer with this email already exists in this tenant.",
        )

    engineer = Engineer(
        tenant_id=t_id,
        name=payload.name,
        email=payload.email,
        skills=payload.skills,
        availability_status=payload.availability_status,
    )
    db.add(engineer)
    db.commit()
    db.refresh(engineer)

    return EngineerResponse.model_validate(engineer)


@router.patch(
    "/{engineer_id}",
    response_model=EngineerResponse,
    summary="Update engineer details or availability",
)
def update_engineer(
    engineer_id: str,
    payload: EngineerUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireEngineerUpdate,
) -> EngineerResponse:
    """Update engineer fields with tenant isolation."""
    engineer = db.get(Engineer, engineer_id)
    if engineer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Engineer not found."
        )

    verify_tenant_access(current_user, engineer.tenant_id)

    if payload.name is not None:
        engineer.name = payload.name

    if payload.email is not None:
        # Guard against email collision within tenant
        collision = db.scalar(
            select(Engineer).where(
                Engineer.tenant_id == engineer.tenant_id,
                Engineer.email == payload.email,
                Engineer.id != engineer_id,
            )
        )
        if collision is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Another engineer with this email already exists in this tenant."
                ),
            )
        engineer.email = payload.email

    if payload.skills is not None:
        engineer.skills = payload.skills

    if payload.availability_status is not None:
        if payload.availability_status not in VALID_AVAILABILITY_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Invalid availability_status. Must be one of: "
                    f"{sorted(VALID_AVAILABILITY_STATUSES)}"
                ),
            )
        engineer.availability_status = payload.availability_status

    db.commit()
    db.refresh(engineer)

    return EngineerResponse.model_validate(engineer)
