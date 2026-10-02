"""Audit logging for agent and human-in-the-loop events (Day 9).

Reuses the Day 1 :class:`~db.models.AuditLog` table and the existing
:func:`auth.audit.log_security_event` sanitiser, so credentials can never be
written into audit metadata.

Audit rows are append-only: nothing in the application updates or deletes them,
and the read API exposes no mutation endpoints.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from auth.audit import log_security_event


class AuditAction(StrEnum):
    """Canonical audit actions for agent and HITL activity."""

    AGENT_ACTION_PROPOSED = "AGENT_ACTION_PROPOSED"
    APPROVAL_CREATED = "APPROVAL_CREATED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_CANCELLED = "APPROVAL_CANCELLED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    AGENT_ACTION_EXECUTED = "AGENT_ACTION_EXECUTED"
    AGENT_ACTION_FAILED = "AGENT_ACTION_FAILED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    KNOWLEDGE_DOCUMENT_CHANGED = "KNOWLEDGE_DOCUMENT_CHANGED"


def log_agent_event(
    session: Session,
    *,
    tenant_id: str,
    action: AuditAction,
    resource_type: str,
    resource_id: str,
    result: str = "success",
    actor_user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record one agent/HITL audit event.

    ``actor_user_id`` stays ``None`` for autonomous agent actions; the acting
    agent is recorded in metadata instead, so the audit trail distinguishes a
    human reviewer from an agent.
    """

    log_security_event(
        session=session,
        action=action.value,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        result=result,
        metadata=metadata,
    )
