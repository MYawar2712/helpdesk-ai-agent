"""Triage Agent ticket tools.

These implement the Day 7 rule that a conversation maps to *one* ticket: triage
reuses the customer's active ticket when one exists and only creates a new
ticket for a genuinely new issue. Every operation is ownership-checked by
:class:`~services.operations.HelpdeskOperationsService`.
"""

from __future__ import annotations

from typing import Any

from agents.context import AgentContext, AgentToolError
from agents.tools.base import JOB, SUPPORT, TRIAGE, ToolRegistry
from db.data_layer import HelpdeskDataRepository
from models import normalize_ticket_category
from services.operations import (
    AuthorizationError,
    BusinessRuleError,
    HelpdeskOperationsService,
)

_SCOPE = frozenset({TRIAGE, JOB, SUPPORT})

#: Statuses that mean a ticket is still part of an open conversation.
ACTIVE_TICKET_STATUSES = ("open", "in_progress", "waiting_for_customer")


def _service(repository: HelpdeskDataRepository) -> HelpdeskOperationsService:
    return HelpdeskOperationsService(repository.sql_connection)


def find_active_ticket(
    repository: HelpdeskDataRepository, ctx: AgentContext
) -> dict[str, Any]:
    """Return the customer's active ticket, if any, for ticket reuse."""

    ticket = _service(repository).find_active_customer_ticket(ctx.identity)
    if ticket is None:
        return {
            "found": False,
            "ticket": None,
            "message": "No active ticket found for this customer.",
        }
    return {
        "found": True,
        "ticket": ctx.require_same_tenant(ticket) or {},
        "message": f"Existing active ticket {ticket['id']} ({ticket['status']}).",
    }


def create_ticket(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    *,
    title: str,
    description: str,
    category: str | None = None,
    priority: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    """Create a helpdesk ticket representing the customer's issue."""

    if not title.strip():
        raise AgentToolError("ticket title is required")

    try:
        ticket = _service(repository).create_ticket(
            ctx.identity,
            title=title.strip(),
            description=description,
            category=normalize_ticket_category(category) if category else None,
            priority=priority,
            intent=intent,
        )
    except (BusinessRuleError, AuthorizationError, ValueError) as error:
        raise AgentToolError(str(error)) from error

    return {
        "found": True,
        "ticket": ctx.require_same_tenant(ticket) or {},
        "message": f"Created ticket {ticket['id']}.",
    }


def update_ticket(
    repository: HelpdeskDataRepository,
    ctx: AgentContext,
    ticket_id: str,
    note: str,
    status: str | None = None,
    resolution: str | None = None,
    handled_by: str | None = None,
) -> dict[str, Any]:
    """Append a follow-up note to an owned ticket instead of creating a new one."""

    try:
        ticket = _service(repository).append_ticket_note(
            ctx.identity,
            ticket_id,
            note=note,
            status=status,
            resolution=resolution,
            handled_by=handled_by,
        )
    except (BusinessRuleError, AuthorizationError) as error:
        raise AgentToolError(str(error)) from error
    return {
        "found": True,
        "ticket": ctx.require_same_tenant(ticket) or {},
        "message": f"Updated existing ticket {ticket_id}.",
    }


def register_ticket_tools(
    registry: ToolRegistry, repository: HelpdeskDataRepository
) -> ToolRegistry:
    """Register ticket tools used by the Triage Agent."""

    registry.add(
        "find_active_ticket",
        "Find the customer's existing active ticket so follow-up messages "
        "update it instead of creating a new ticket.",
        lambda ctx: find_active_ticket(repository, ctx),
        scope=_SCOPE,
    )
    registry.add(
        "create_ticket",
        "Create a new helpdesk ticket for the customer's issue.",
        lambda ctx, title, description, category=None, priority=None, intent=None: (
            create_ticket(
                repository,
                ctx,
                title=title,
                description=description,
                category=category,
                priority=priority,
                intent=intent,
            )
        ),
        scope=frozenset({TRIAGE}),
        mutates=True,
        required_arguments=("title", "description"),
    )
    registry.add(
        "update_ticket",
        "Append context to an existing active ticket owned by the customer.",
        lambda ctx, ticket_id, note, status=None, resolution=None, handled_by=None: (
            update_ticket(
                repository,
                ctx,
                ticket_id,
                note,
                status=status,
                resolution=resolution,
                handled_by=handled_by,
            )
        ),
        scope=frozenset({TRIAGE}),
        mutates=True,
        required_arguments=("ticket_id", "note"),
    )
    return registry
