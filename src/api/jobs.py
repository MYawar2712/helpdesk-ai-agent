"""Tenant-scoped Job Management APIs (Day 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dto import JobAssignDTO, JobCreateDTO, JobResponse, JobUpdateDTO
from api.pagination import PaginatedResponse, build_paginated_response
from auth.dependencies import (
    require_permission,
    verify_customer_access,
    verify_tenant_access,
)
from auth.rbac import Permission
from db.models import Customer, Engineer, Job, User
from db.session import get_db

router = APIRouter(prefix="/jobs", tags=["jobs"])

_RequireJobRead = Depends(require_permission(Permission.JOB_READ.value))
_RequireJobCreate = Depends(require_permission(Permission.JOB_CREATE.value))
_RequireJobUpdate = Depends(require_permission(Permission.JOB_UPDATE.value))
_RequireJobCancel = Depends(require_permission(Permission.JOB_CANCEL.value))
_RequireJobAssign = Depends(require_permission(Permission.JOB_ASSIGN.value))

VALID_JOB_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"assigned", "in_progress", "cancelled"},
    "assigned": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


@router.get(
    "",
    response_model=PaginatedResponse[JobResponse],
    summary="List tenant jobs with pagination",
)
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireJobRead,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: str | None = Query(default=None),
) -> PaginatedResponse[JobResponse]:
    """List jobs scoped to current_user's tenant."""
    t_id = current_user.tenant_id
    verify_customer_access(
        current_user, customer_id or getattr(current_user, "customer_id", "")
    )

    query = select(Job).where(Job.tenant_id == t_id)
    if status_filter:
        query = query.where(Job.status == status_filter)
    if customer_id:
        query = query.where(Job.customer_id == customer_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    offset = (page - 1) * page_size
    items = list(db.scalars(query.offset(offset).limit(page_size)).all())

    return build_paginated_response(
        items=[JobResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get job details by ID",
)
def get_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireJobRead,
) -> JobResponse:
    """Get single job with tenant and customer isolation checks."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )

    verify_tenant_access(current_user, job.tenant_id)
    verify_customer_access(current_user, job.customer_id)

    return JobResponse.model_validate(job)


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new job",
)
def create_job(
    payload: JobCreateDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireJobCreate,
) -> JobResponse:
    """Create job validating customer and engineer tenant boundaries."""
    t_id = current_user.tenant_id

    customer = db.get(Customer, payload.customer_id)
    if customer is None or customer.tenant_id != t_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer not found in current tenant.",
        )

    verify_customer_access(current_user, payload.customer_id)

    if payload.assigned_engineer_id:
        engineer = db.get(Engineer, payload.assigned_engineer_id)
        if engineer is None or engineer.tenant_id != t_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Engineer not found in current tenant.",
            )

    job = Job(
        tenant_id=t_id,
        customer_id=payload.customer_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        status="assigned" if payload.assigned_engineer_id else "pending",
        assigned_engineer_id=payload.assigned_engineer_id,
        scheduled_at=payload.scheduled_at,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return JobResponse.model_validate(job)


@router.patch(
    "/{job_id}",
    response_model=JobResponse,
    summary="Update job status or details",
)
def update_job(
    job_id: str,
    payload: JobUpdateDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireJobUpdate,
) -> JobResponse:
    """Update job fields with status transition and engineer validation."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )

    verify_tenant_access(current_user, job.tenant_id)
    verify_customer_access(current_user, job.customer_id)

    if payload.status is not None:
        new_status = payload.status
        allowed_next = VALID_JOB_TRANSITIONS.get(job.status, set())
        if new_status != job.status and new_status not in allowed_next:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid job status transition from '{job.status}' "
                    f"to '{new_status}'."
                ),
            )
        job.status = new_status

    if payload.assigned_engineer_id is not None:
        engineer = db.get(Engineer, payload.assigned_engineer_id)
        if engineer is None or engineer.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Engineer not found in current tenant.",
            )
        job.assigned_engineer_id = payload.assigned_engineer_id

    if payload.title is not None:
        job.title = payload.title
    if payload.description is not None:
        job.description = payload.description
    if payload.priority is not None:
        job.priority = payload.priority
    if payload.scheduled_at is not None:
        job.scheduled_at = payload.scheduled_at

    db.commit()
    db.refresh(job)
    return JobResponse.model_validate(job)


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
    summary="Cancel a job",
)
def cancel_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireJobCancel,
) -> JobResponse:
    """Cancel job with status transition and tenant check."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )

    verify_tenant_access(current_user, job.tenant_id)
    verify_customer_access(current_user, job.customer_id)

    if job.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completed jobs cannot be cancelled.",
        )

    job.status = "cancelled"
    db.commit()
    db.refresh(job)

    return JobResponse.model_validate(job)


@router.post(
    "/{job_id}/assign",
    response_model=JobResponse,
    summary="Assign an engineer to a job",
)
def assign_job(
    job_id: str,
    payload: JobAssignDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireJobAssign,
) -> JobResponse:
    """Assign engineer validating tenant isolation."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )

    verify_tenant_access(current_user, job.tenant_id)
    verify_customer_access(current_user, job.customer_id)

    engineer = db.get(Engineer, payload.engineer_id)
    if engineer is None or engineer.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Engineer not found in current tenant.",
        )

    job.assigned_engineer_id = engineer.id
    if job.status == "pending":
        job.status = "assigned"

    db.commit()
    db.refresh(job)

    return JobResponse.model_validate(job)
