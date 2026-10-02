"""Invoice Agent tools.

Invoice creation and status changes go through
:class:`~services.operations.HelpdeskOperationsService`, which verifies customer
ownership, the underlying job's ownership, and legal status transitions before
writing. Financial disputes are never settled by these tools — they are routed
to human escalation by triage instead.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from agents.context import AgentContext, AgentToolError
from agents.tools.base import INVOICE, SUPPORT, ToolRegistry
from db.data_layer import HelpdeskDataRepository
from services.operations import (
    AuthorizationError,
    BusinessRuleError,
    HelpdeskOperationsService,
)

_READ_SCOPE = frozenset({INVOICE, SUPPORT})
_WRITE_SCOPE = frozenset({INVOICE})


def _service(repository: HelpdeskDataRepository) -> HelpdeskOperationsService:
    return HelpdeskOperationsService(repository.sql_connection)


def _normalize_invoice_id(invoice_id: str) -> str:
    invoice_id = invoice_id.strip()
    if invoice_id.isdigit():
        return f"invoice-{invoice_id}"
    return invoice_id


def get_invoice(
    repository: HelpdeskDataRepository, ctx: AgentContext, invoice_id: str
) -> dict[str, Any]:
    """Return one invoice owned by the authenticated customer."""

    try:
        invoice = _service(repository).get_customer_invoice(
            ctx.identity, _normalize_invoice_id(invoice_id)
        )
    except LookupError as error:
        raise AgentToolError(
            "No invoice matching that ID was found on your account."
        ) from error
    return {
        "found": True,
        "invoice": ctx.require_same_tenant(invoice) or {},
        "message": f"Invoice {invoice['id']} is '{invoice['status']}' with a "
        f"total of {invoice.get('total', invoice.get('amount'))}.",
    }


def get_customer_invoices(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    only_outstanding: bool = False,
) -> dict[str, Any]:
    """List invoices belonging to the authenticated customer."""

    invoices = _service(repository).list_customer_invoices(
        ctx.identity, only_outstanding=bool(only_outstanding)
    )
    scoped = [ctx.require_same_tenant(invoice) or {} for invoice in invoices]
    if only_outstanding:
        message = f"You have {len(scoped)} outstanding invoice(s)."
    else:
        message = f"You have {len(scoped)} invoice(s) on your account."
    return {
        "found": bool(scoped),
        "invoices": scoped,
        "count": len(scoped),
        "message": message,
    }


def create_invoice(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    *,
    job_id: str,
    amount: str,
    due_date: str | None = None,
) -> dict[str, Any]:
    """Create an invoice for a job the customer owns."""

    resolved_due = due_date or (date.today() + timedelta(days=14)).isoformat()
    try:
        invoice = _service(repository).create_customer_invoice(
            ctx.identity,
            job_id=job_id,
            amount=amount,
            due_date=resolved_due,
        )
    except (BusinessRuleError, AuthorizationError) as error:
        raise AgentToolError(str(error)) from error
    return {
        "found": True,
        "invoice": ctx.require_same_tenant(invoice) or {},
        "message": f"Created invoice {invoice['id']} for job {invoice['job_id']}.",
    }


def update_invoice(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    invoice_id: str,
    new_status: str,
) -> dict[str, Any]:
    """Update an owned invoice's status, enforcing legal transitions."""

    try:
        result = _service(repository).update_customer_invoice_status(
            ctx.identity, _normalize_invoice_id(invoice_id), new_status
        )
    except (BusinessRuleError, ValueError) as error:
        raise AgentToolError(str(error)) from error
    return {
        "found": True,
        "invoice": ctx.require_same_tenant(result["invoice"]) or {},
        "message": f"Invoice {invoice_id} is now '{new_status}'.",
    }


def register_invoice_tools(
    registry: ToolRegistry, repository: HelpdeskDataRepository
) -> ToolRegistry:
    """Register every Invoice Agent tool against *repository*."""

    registry.add(
        "get_invoice",
        "Get details for one invoice owned by the customer.",
        lambda ctx, invoice_id: get_invoice(repository, ctx, invoice_id),
        scope=_READ_SCOPE,
        required_arguments=("invoice_id",),
    )
    registry.add(
        "get_customer_invoices",
        "List the customer's invoices; optionally only outstanding ones.",
        lambda ctx, only_outstanding=False: get_customer_invoices(
            repository, ctx, only_outstanding
        ),
        scope=_READ_SCOPE,
    )
    registry.add(
        "create_invoice",
        "Create an invoice for a job the customer owns.",
        lambda ctx, job_id, amount, due_date=None: create_invoice(
            repository, ctx, job_id=job_id, amount=amount, due_date=due_date
        ),
        scope=_WRITE_SCOPE,
        mutates=True,
        required_arguments=("job_id", "amount"),
    )
    registry.add(
        "update_invoice",
        "Change the status of an invoice the customer owns.",
        lambda ctx, invoice_id, new_status: update_invoice(
            repository, ctx, invoice_id, new_status
        ),
        scope=_WRITE_SCOPE,
        mutates=True,
        required_arguments=("invoice_id", "new_status"),
    )
    return registry
