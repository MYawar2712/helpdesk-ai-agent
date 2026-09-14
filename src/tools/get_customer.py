"""Tool for looking up a helpdesk customer."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from db.data_layer import HelpdeskDataRepository


def get_customer(repository: HelpdeskDataRepository, id: str) -> dict[str, Any]:
    """Return a customer record, or a consistent not-found result."""
    if not isinstance(id, str) or not id.strip():
        raise ValueError("id must be a non-empty string")
    customer = repository.get_customer(id)
    if customer is None:
        return {"found": False, "customer": None, "error": "Customer not found"}
    return {
        "found": True,
        "customer": {
            field: customer[field] for field in ("id", "name", "company", "created_at")
        },
    }


def create_get_customer_tool(repository: HelpdeskDataRepository) -> StructuredTool:
    """Create the typed LangChain tool bound to a repository."""

    def lookup_customer(id: str) -> dict[str, Any]:
        """Look up customer details using the customer ID."""
        return get_customer(repository, id)

    return StructuredTool.from_function(
        func=lookup_customer,
        name="get_customer",
        description="Get details for one customer using the customer ID.",
    )
