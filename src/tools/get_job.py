"""Tool for looking up a helpdesk job."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from db.data_layer import HelpdeskDataRepository


def get_job(repository: HelpdeskDataRepository, id: str) -> dict[str, Any]:
    """Return a job record, or a consistent not-found result."""
    if not isinstance(id, str) or not id.strip():
        raise ValueError("id must be a non-empty string")
    if id.isdigit():
        id = f"job-{id}"
    job = repository.get_job(id)
    if job is None:
        return {"found": False, "job": None, "error": "Job not found"}
    return {"found": True, "job": job}


def create_get_job_tool(repository: HelpdeskDataRepository) -> StructuredTool:
    """Create the typed LangChain tool bound to a repository."""

    def lookup_job(id: str) -> dict[str, Any]:
        """Look up a job by its ID, including its status and schedule."""
        return get_job(repository, id)

    return StructuredTool.from_function(
        func=lookup_job,
        name="get_job",
        description="Get the status and details for one job using its ID.",
    )
