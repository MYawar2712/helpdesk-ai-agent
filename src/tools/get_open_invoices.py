"""Tool for retrieving a customer's unpaid invoices."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from db.data_layer import HelpdeskDataRepository


def get_open_invoices(
    repository: HelpdeskDataRepository, customer_id: str
) -> dict[str, Any]:
    """Return unpaid and overdue invoices for a customer."""
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise ValueError("customer_id must be a non-empty string")
    if customer_id.isdigit():
        customer_id = f"customer-{customer_id}"
    if repository.get_customer(customer_id) is None:
        return {"found": False, "invoices": [], "error": "Customer not found"}
    return {
        "found": True,
        "invoices": repository.get_open_invoices(customer_id),
    }


def create_get_open_invoices_tool(
    repository: HelpdeskDataRepository,
) -> StructuredTool:
    """Create the typed LangChain tool bound to a repository."""

    def lookup_open_invoices(customer_id: str) -> dict[str, Any]:
        """Get unpaid and overdue invoices using a customer ID."""
        return get_open_invoices(repository, customer_id)

    return StructuredTool.from_function(
        func=lookup_open_invoices,
        name="get_open_invoices",
        description="Get a customer's unpaid and overdue invoices by customer ID.",
    )
