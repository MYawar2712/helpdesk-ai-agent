"""LangChain tool for cancelling an existing customer job.

The tool calls the authorised HelpdeskOperationsService — it never modifies
the database directly and always enforces customer-ownership checks.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from db.data_layer import HelpdeskDataRepository
from services.operations import AuthorizationError, HelpdeskOperationsService


class CancelJobInput(BaseModel):
    """Input schema for the cancel_job tool."""

    customer_id: str = Field(description="The ID of the requesting customer.")
    job_id: str | None = Field(
        default=None,
        description=(
            "Optional specific job ID to cancel (e.g. 'job-123'). "
            "If omitted, all active scheduled/pending jobs for the customer are "
            "cancelled."
        ),
    )


def cancel_job(
    repository: HelpdeskDataRepository,
    customer_id: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Cancel one or all active jobs for a customer.

    Enforces ownership — only jobs belonging to ``customer_id`` are affected.
    Returns a summary dict with the list of cancelled jobs.
    """
    if not customer_id or not customer_id.strip():
        return {
            "found": False,
            "cancelled_jobs": [],
            "error": "customer_id is required",
        }

    if not job_id or not job_id.strip():
        return {
            "found": False,
            "cancelled_jobs": [],
            "count": 0,
            "requires_job_id": True,
            "message": (
                "Ask the customer which specific job ID they want to cancel. "
                "Do not cancel all jobs."
            ),
        }

    svc = HelpdeskOperationsService(repository.sql_connection)
    try:
        cancelled = svc.cancel_customer_scheduled_jobs(customer_id, job_id=job_id)
    except AuthorizationError as exc:
        return {
            "found": False,
            "cancelled_jobs": [],
            "error": str(exc),
            "forbidden": True,
        }

    if cancelled:
        return {
            "found": True,
            "cancelled_jobs": cancelled,
            "count": len(cancelled),
            "message": (
                f"Successfully cancelled {len(cancelled)} job(s): "
                + ", ".join(j["id"] for j in cancelled)
            ),
        }

    if job_id:
        return {
            "found": False,
            "cancelled_jobs": [],
            "count": 0,
            "message": (
                f"No active job '{job_id}' found for customer {customer_id}. "
                "The job may not exist, may already be cancelled/completed, "
                "or may not belong to this customer."
            ),
        }

    message = f"No active scheduled/pending jobs found for customer {customer_id}."
    return {
        "found": False,
        "cancelled_jobs": [],
        "count": 0,
        "message": message,
    }


def create_cancel_job_tool(repository: HelpdeskDataRepository) -> StructuredTool:
    """Create a cancel_job tool bound to the given repository."""

    def _cancel_job(customer_id: str, job_id: str | None = None) -> dict[str, Any]:
        """Cancel an existing job for a customer. Does NOT create a new job."""
        return cancel_job(repository, customer_id, job_id)

    return StructuredTool.from_function(
        func=_cancel_job,
        name="cancel_job",
        description=(
            "Cancel an existing scheduled or pending job for a customer. "
            "Use when the customer says 'cancel my job', 'I want to cancel', etc. "
            "Provide customer_id and optionally a specific job_id. "
            "NEVER creates a new job — only cancels existing ones."
        ),
        args_schema=CancelJobInput,
    )
