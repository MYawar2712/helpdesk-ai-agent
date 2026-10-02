"""Job Agent tools.

Every handler receives the server-derived :class:`~agents.context.AgentContext`
and delegates to :class:`~services.operations.HelpdeskOperationsService`, which
re-validates customer ownership and business rules on each call. No handler
performs authorization itself and none trusts an identity from model output.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agents.context import AgentContext, AgentToolError
from agents.tools.base import JOB, SUPPORT, ToolRegistry
from db.data_layer import HelpdeskDataRepository
from services.operations import (
    AuthorizationError,
    BusinessRuleError,
    HelpdeskOperationsService,
    infer_required_skill,
)
from utils.date_parser import parse_natural_datetime

#: Scope allowed to invoke job tools. Triage may read to resolve identifiers but
#: only the Job Agent may mutate.
_READ_SCOPE = frozenset({JOB, SUPPORT})
_WRITE_SCOPE = frozenset({JOB})

DEFAULT_SERVICE_AREA = "London"
_ENGINEER_SKILLS = ("technician", "plumber", "HVAC", "electrical", "sanitary")


def _service(repository: HelpdeskDataRepository) -> HelpdeskOperationsService:
    return HelpdeskOperationsService(repository.sql_connection)


def _normalize_job_id(job_id: str) -> str:
    """Allow customers to quote a bare numeric id."""

    job_id = job_id.strip()
    if job_id.isdigit():
        return f"job-{job_id}"
    return job_id


def _get_job(
    repository: HelpdeskDataRepository, ctx: AgentContext, job_id: str
) -> dict[str, Any]:
    """Return a job owned by the authenticated customer, or raise."""

    try:
        job = _service(repository).get_customer_job(
            ctx.identity, _normalize_job_id(job_id)
        )
    except LookupError as error:
        raise AgentToolError(
            "No job matching that ID was found on your account."
        ) from error
    return ctx.require_same_tenant(job) or {}


def get_job(
    repository: HelpdeskDataRepository, ctx: AgentContext, job_id: str
) -> dict[str, Any]:
    """Look up one job belonging to the authenticated customer."""

    job = _get_job(repository, ctx, job_id)
    return {
        "found": True,
        "job": job,
        "message": f"Job {job['id']} is currently '{job['status']}'.",
    }


def get_customer_jobs(
    repository: HelpdeskDataRepository, ctx: AgentContext
) -> dict[str, Any]:
    """List the authenticated customer's jobs."""

    rows = repository.sql_connection.execute(
        "SELECT * FROM jobs WHERE customer_id = ? ORDER BY created_at DESC, id",
        (ctx.customer_id,),
    ).fetchall()
    jobs = [ctx.require_same_tenant(dict(row)) or {} for row in rows]
    return {
        "found": bool(jobs),
        "jobs": jobs,
        "count": len(jobs),
        "message": (
            f"Found {len(jobs)} job(s) on your account."
            if jobs
            else "You do not currently have any jobs."
        ),
    }


def cancel_job(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    job_id: str,
    ticket_id: str | None = None,
) -> dict[str, Any]:
    """Cancel an active job owned by the authenticated customer."""

    service = _service(repository)
    normalized = _normalize_job_id(job_id)
    try:
        cancelled = service.cancel_customer_scheduled_jobs(
            ctx.customer_id, job_id=normalized
        )
    except AuthorizationError as error:
        raise AgentToolError(str(error)) from error

    if not cancelled:
        return {
            "found": False,
            "cancelled_jobs": [],
            "message": (
                f"No active job '{normalized}' was found on your account. It may "
                "already be cancelled or completed."
            ),
        }

    if ticket_id:
        try:
            service.link_ticket_to_job(ticket_id, cancelled[0]["id"])
        except (AuthorizationError, LookupError):
            # Linking is best-effort; the cancellation itself already succeeded.
            pass

    return {
        "found": True,
        "cancelled_jobs": cancelled,
        "message": "Cancelled job(s): "
        + ", ".join(job["id"] for job in cancelled)
        + ".",
    }


def update_job_status(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    job_id: str,
    new_status: str,
) -> dict[str, Any]:
    """Update a job status after validating the ownership and the transition."""

    try:
        result = _service(repository).update_customer_job_status(
            ctx.identity, _normalize_job_id(job_id), new_status
        )
    except BusinessRuleError as error:
        raise AgentToolError(str(error)) from error
    return {
        "found": True,
        "job": ctx.require_same_tenant(result["job"]) or {},
        "message": f"Job {job_id} is now '{new_status}'.",
    }


def reschedule_job(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    job_id: str,
    new_time: str,
) -> dict[str, Any]:
    """Move a job's appointment time, parsing natural-language dates."""

    parsed = parse_natural_datetime(new_time)
    if parsed is None:
        raise AgentToolError(
            f"Could not understand the requested time '{new_time}'. "
            "Please give an explicit date and time."
        )
    try:
        result = _service(repository).reschedule_customer_job(
            ctx.identity, _normalize_job_id(job_id), parsed.isoformat()
        )
    except BusinessRuleError as error:
        raise AgentToolError(str(error)) from error
    return {
        "found": True,
        "job": ctx.require_same_tenant(result["job"]) or {},
        "message": f"Job {job_id} has been rescheduled to {parsed.isoformat()}.",
    }


def create_job(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    *,
    title: str,
    description: str,
    ticket_id: str | None = None,
    required_skill: str | None = None,
    service_area: str = DEFAULT_SERVICE_AREA,
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    """Create a service job for the customer and auto-assign an engineer.

    A new Job is only created for concrete service requests; informational
    questions never reach this tool (triage routes those to the Support Agent).
    """

    skill = required_skill or infer_required_skill(description) or "technician"
    if skill not in _ENGINEER_SKILLS:
        skill = "technician"

    parsed_schedule: str | None = None
    if scheduled_at:
        parsed = parse_natural_datetime(scheduled_at)
        if parsed is None:
            raise AgentToolError(
                f"Could not understand the requested time '{scheduled_at}'."
            )
        parsed_schedule = parsed.isoformat()

    service = _service(repository)
    try:
        if ticket_id:
            created = service.create_job_for_ticket(
                ctx.identity,
                ticket_id=ticket_id,
                title=title,
                description=description,
                required_skill=skill,
                service_area=service_area,
                scheduled_at=parsed_schedule,
            )
            job = created["job"]
        else:
            job = service.create_job(
                ctx.identity,
                title=title,
                description=description,
                required_skill=skill,
                service_area=service_area,
                scheduled_at=parsed_schedule,
            )
    except (BusinessRuleError, AuthorizationError) as error:
        raise AgentToolError(str(error)) from error

    engineer_id = job.get("assigned_engineer_id")
    return {
        "found": True,
        "job": ctx.require_same_tenant(job) or {},
        "message": (
            f"Created job {job['id']}"
            + (f" and assigned engineer {engineer_id}." if engineer_id else ".")
        ),
    }


def assign_engineer(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    job_id: str,
    engineer_id: str,
) -> dict[str, Any]:
    """Assign an eligible engineer to a job the customer owns.

    Ownership is checked *before* assignment because
    :meth:`HelpdeskOperationsService.assign_engineer` is a reviewer-facing
    operation that does not itself scope by customer.
    """

    normalized = _normalize_job_id(job_id)
    _get_job(repository, ctx, normalized)  # raises if not owned

    engineer = _find_engineer_row(repository.sql_connection, engineer_id)
    if engineer is None:
        raise AgentToolError(f"No engineer found with ID {engineer_id}.")

    try:
        job = _service(repository).assign_engineer(
            job_id=normalized, engineer_id=engineer_id, reviewer="ai_supervisor"
        )
    except (BusinessRuleError, LookupError) as error:
        raise AgentToolError(str(error)) from error
    return {
        "found": True,
        "job": job,
        "message": f"Assigned engineer {engineer_id} to job {normalized}.",
    }


def _find_engineer_row(
    connection: sqlite3.Connection, engineer_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM engineers WHERE id = ?", (engineer_id,)
    ).fetchone()


def get_engineers(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    required_skill: str | None = None,
) -> dict[str, Any]:
    """List active engineers, optionally filtered by skill."""

    connection = repository.sql_connection
    if required_skill:
        rows = connection.execute(
            """SELECT DISTINCT engineers.* FROM engineers
            JOIN engineer_skills ON engineer_skills.engineer_id = engineers.id
            WHERE engineers.active = 1 AND engineer_skills.skill = ?
            ORDER BY engineers.current_workload ASC, engineers.id""",
            (required_skill,),
        ).fetchall()
    else:
        rows = connection.execute(
            """SELECT * FROM engineers WHERE active = 1
            ORDER BY current_workload ASC, id"""
        ).fetchall()

    engineers = [
        {
            "id": row["id"],
            "name": row["name"],
            "service_area": row["service_area"],
            "current_workload": row["current_workload"],
        }
        for row in rows
    ]
    return {
        "found": bool(engineers),
        "engineers": engineers,
        "count": len(engineers),
        "message": (
            f"Found {len(engineers)} available engineer(s)."
            if engineers
            else "No engineers are currently available."
        ),
    }


def register_job_tools(
    registry: ToolRegistry, repository: HelpdeskDataRepository
) -> ToolRegistry:
    """Register every Job Agent tool against *repository*."""

    registry.add(
        "get_job",
        "Get the status and details of one job owned by the customer.",
        lambda ctx, job_id: get_job(repository, ctx, job_id),
        scope=_READ_SCOPE,
        required_arguments=("job_id",),
    )
    registry.add(
        "get_customer_jobs",
        "List all jobs belonging to the customer.",
        lambda ctx: get_customer_jobs(repository, ctx),
        scope=_READ_SCOPE,
    )
    registry.add(
        "cancel_job",
        "Cancel an active job owned by the customer.",
        lambda ctx, job_id, ticket_id=None: cancel_job(
            repository, ctx, job_id, ticket_id
        ),
        scope=_WRITE_SCOPE,
        mutates=True,
        required_arguments=("job_id",),
    )
    registry.add(
        "update_job_status",
        "Change the status of a job owned by the customer.",
        lambda ctx, job_id, new_status: update_job_status(
            repository, ctx, job_id, new_status
        ),
        scope=_WRITE_SCOPE,
        mutates=True,
        required_arguments=("job_id", "new_status"),
    )
    registry.add(
        "reschedule_job",
        "Move a job's appointment to a new date and time.",
        lambda ctx, job_id, new_time: reschedule_job(repository, ctx, job_id, new_time),
        scope=_WRITE_SCOPE,
        mutates=True,
        required_arguments=("job_id", "new_time"),
    )

    def _create_job(
        ctx: AgentContext,
        title: str,
        description: str,
        ticket_id: str | None = None,
        required_skill: str | None = None,
        service_area: str = DEFAULT_SERVICE_AREA,
        scheduled_at: str | None = None,
    ) -> dict[str, Any]:
        return create_job(
            repository,
            ctx,
            title=title,
            description=description,
            ticket_id=ticket_id,
            required_skill=required_skill,
            service_area=service_area,
            scheduled_at=scheduled_at,
        )

    registry.add(
        "create_job",
        "Create a new service job and auto-assign an available engineer.",
        _create_job,
        scope=_WRITE_SCOPE,
        mutates=True,
        required_arguments=("title", "description"),
    )
    registry.add(
        "assign_engineer",
        "Assign a specific eligible engineer to a job owned by the customer.",
        lambda ctx, job_id, engineer_id: assign_engineer(
            repository, ctx, job_id, engineer_id
        ),
        scope=_WRITE_SCOPE,
        mutates=True,
        required_arguments=("job_id", "engineer_id"),
    )
    registry.add(
        "get_engineers",
        "List available engineers, optionally filtered by required skill.",
        lambda ctx, required_skill=None: get_engineers(repository, ctx, required_skill),
        scope=_READ_SCOPE,
    )
    return registry
