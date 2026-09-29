"""Dashboard Summary API endpoints (Day 4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dto import DashboardSummaryResponse
from auth.dependencies import require_permission
from auth.rbac import Permission
from db.models import Customer, Engineer, Invoice, Job, Ticket, User
from db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_RequireTenantRead = Depends(require_permission(Permission.TENANT_READ.value))


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    summary="Get tenant aggregate dashboard metrics",
)
def get_dashboard_summary(
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireTenantRead,
) -> DashboardSummaryResponse:
    """Return SQL-aggregated metrics scoped strictly to current_user's tenant_id."""
    t_id = current_user.tenant_id

    # 1. Total Customers
    cust_count = (
        db.scalar(select(func.count(Customer.id)).where(Customer.tenant_id == t_id))
        or 0
    )

    # 2. Open Tickets (status != 'closed' and status != 'resolved')
    open_tickets_count = (
        db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.tenant_id == t_id,
                Ticket.status.notin_(["closed", "resolved"]),
            )
        )
        or 0
    )

    # 3. Active Jobs (status in ['pending', 'assigned', 'in_progress'])
    active_jobs_count = (
        db.scalar(
            select(func.count(Job.id)).where(
                Job.tenant_id == t_id,
                Job.status.in_(["pending", "assigned", "in_progress"]),
            )
        )
        or 0
    )

    # 4. Pending Invoices (status = 'unpaid' or status = 'overdue')
    pending_invoices_count = (
        db.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == t_id,
                Invoice.status.in_(["unpaid", "overdue"]),
            )
        )
        or 0
    )

    # 5. Available Engineers (availability_status = 'available')
    avail_engineers_count = (
        db.scalar(
            select(func.count(Engineer.id)).where(
                Engineer.tenant_id == t_id,
                Engineer.availability_status == "available",
            )
        )
        or 0
    )

    return DashboardSummaryResponse(
        customers=cust_count,
        open_tickets=open_tickets_count,
        active_jobs=active_jobs_count,
        pending_invoices=pending_invoices_count,
        available_engineers=avail_engineers_count,
    )
