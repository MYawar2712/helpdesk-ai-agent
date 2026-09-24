"""LangChain tool for updating the status of an existing customer job.

All mutations go through HelpdeskOperationsService which enforces
customer-ownership and validates allowed status transitions.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from db.data_layer import HelpdeskDataRepository
from services.operations import (
    AuthorizationError,
    BusinessRuleError,
    CustomerIdentity,
    HelpdeskOperationsService,
)


class UpdateJobStatusInput(BaseModel):
    """Input schema for the update_job_status tool."""

    customer_id: str = Field(description="The ID of the requesting customer.")
    job_id: str = Field(description="The ID of the job to update (e.g. 'job-123').")
    new_status: str = Field(
        description=(
            "The new status for the job. "
            "Allowed values: 'cancelled', 'scheduled', 'in_progress', 'completed'."
        )
    )


def update_job_status(
    repository: HelpdeskDataRepository,
    customer_id: str,
    job_id: str,
    new_status: str,
) -> dict[str, Any]:
    """Update the status of an existing job with ownership and transition checks."""
    if not customer_id.strip() or not job_id.strip():
        return {"found": False, "error": "customer_id and job_id are required"}

    svc = HelpdeskOperationsService(repository.sql_connection)
    try:
        return svc.update_customer_job_status(
            CustomerIdentity(customer_id=customer_id),
            job_id,
            new_status,
        )
    except LookupError as exc:
        return {"found": False, "error": str(exc)}
    except AuthorizationError as exc:
        return {"found": False, "error": str(exc), "forbidden": True}
    except BusinessRuleError as exc:
        return {"found": True, "error": str(exc)}


def create_update_job_status_tool(repository: HelpdeskDataRepository) -> StructuredTool:
    """Create an update_job_status tool bound to the given repository."""

    def _update_job_status(
        customer_id: str, job_id: str, new_status: str
    ) -> dict[str, Any]:
        """Update the status of a customer's existing job."""
        return update_job_status(repository, customer_id, job_id, new_status)

    return StructuredTool.from_function(
        func=_update_job_status,
        name="update_job_status",
        description=(
            "Update the status of an existing job for a customer. "
            "Use for rescheduling, marking in-progress, completing or cancelling "
            "a job. "
            "Enforces customer ownership — cannot modify another customer's job."
        ),
        args_schema=UpdateJobStatusInput,
    )
