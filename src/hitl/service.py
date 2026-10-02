"""Approval workflow service: create, review, and execute exactly once (Day 9).

Execution safety
----------------
An approved action is claimed with a single conditional UPDATE::

    UPDATE approval_requests
       SET status = 'EXECUTING'
     WHERE id = :id AND status = 'APPROVED'

The database decides the winner. A second caller, a network retry, a restarted
worker, or a double LangGraph resume all see zero affected rows and are refused.
That is what makes ``APPROVED -> EXECUTED`` happen at most once, regardless of
how many times the resume path is triggered.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.actions import TERMINAL_STATUSES, AgentAction, ApprovalStatus
from agents.approval_policy import ApprovalRequirement
from db.models import ApprovalRequest
from hitl.audit_events import AuditAction, log_agent_event

#: Default lifetime of a pending approval.
DEFAULT_APPROVAL_TTL = timedelta(hours=24)

#: Parameters that must never be persisted in an approval payload.
_SENSITIVE_KEYS = (
    "password",
    "token",
    "jwt",
    "secret",
    "api_key",
    "authorization",
)


class ApprovalError(RuntimeError):
    """Base error for approval workflow failures."""


class ApprovalNotFound(ApprovalError):
    """The approval does not exist for the requesting tenant."""


class ApprovalConflict(ApprovalError):
    """The approval is not in a state that allows the requested transition."""


class ApprovalExpired(ApprovalError):
    """The approval window has closed."""


def _sanitize(parameters: dict[str, Any]) -> dict[str, Any]:
    """Strip credential-like keys before persisting an action payload."""

    return {
        key: value
        for key, value in (parameters or {}).items()
        if not any(marker in key.lower() for marker in _SENSITIVE_KEYS)
    }


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalise a stored timestamp to an aware UTC datetime.

    SQLite returns naive datetimes even for ``DateTime(timezone=True)`` columns,
    so every comparison against ``datetime.now(UTC)`` must go through here.
    """

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_expired(row: ApprovalRequest, *, now: datetime) -> bool:
    expires_at = _as_utc(row.expires_at)
    return expires_at is not None and expires_at <= now


class ApprovalService:
    """Create and review approval requests for agent actions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Creation ──────────────────────────────────────────────────────────

    def create(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        agent_type: str,
        action: AgentAction,
        requirement: ApprovalRequirement,
        requested_by: str,
        ticket_id: str | None = None,
        ttl: timedelta = DEFAULT_APPROVAL_TTL,
    ) -> ApprovalRequest:
        """Persist a PENDING approval request for *action*.

        Re-creating the same action for the same conversation returns the
        existing row rather than raising, so a replayed graph node cannot spawn
        duplicate requests. The match covers every non-terminal status, not just
        PENDING: a LangGraph node re-runs on resume, and by then the original
        row may already be APPROVED or EXECUTING. Terminal rows (rejected,
        expired, cancelled, executed, failed) are left alone so a genuinely new
        attempt can still be raised.
        """

        existing = self._find_live(tenant_id, conversation_id, action)
        if existing is not None:
            return existing

        now = datetime.now(UTC)
        row = ApprovalRequest(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            ticket_id=ticket_id,
            requested_by=requested_by,
            agent_type=agent_type,
            action_type=action.action_type,
            resource_type=action.resource_type,
            resource_id=action.resource_id,
            payload={
                "parameters": _sanitize(action.parameters),
                "reason": action.reason,
            },
            reason=action.reason,
            risk_level=requirement.risk_level.value,
            status=ApprovalStatus.PENDING.value,
            expires_at=now + ttl,
        )
        self._session.add(row)
        try:
            self._session.commit()
        except IntegrityError:
            # A concurrent creator won the race; reuse their row.
            self._session.rollback()
            duplicate = self._session.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.conversation_id == conversation_id,
                    ApprovalRequest.action_type == action.action_type,
                    ApprovalRequest.status == ApprovalStatus.PENDING.value,
                )
            ).first()
            if duplicate is None:
                raise
            return duplicate
        self._session.refresh(row)

        log_agent_event(
            self._session,
            tenant_id=tenant_id,
            action=AuditAction.APPROVAL_CREATED,
            resource_type="approval_request",
            resource_id=row.id,
            actor_user_id=None,
            metadata={
                "agent_type": agent_type,
                "conversation_id": conversation_id,
                "action_type": action.action_type,
                "risk_level": requirement.risk_level.value,
                "policy_source": requirement.source,
            },
        )
        return row

    # ── Reads ─────────────────────────────────────────────────────────────

    def _find_live(
        self, tenant_id: str, conversation_id: str, action: AgentAction
    ) -> ApprovalRequest | None:
        """Return an existing non-terminal request for the same action.

        This is the idempotency guard. Matching every non-terminal status is
        what stops a resumed graph node from raising a second request for an
        action that is already approved or executing.
        """

        live = [
            status.value
            for status in ApprovalStatus
            if status.value not in TERMINAL_STATUSES
        ]
        return self._session.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.conversation_id == conversation_id,
                ApprovalRequest.action_type == action.action_type,
                ApprovalRequest.resource_type == action.resource_type,
                ApprovalRequest.resource_id == action.resource_id,
                ApprovalRequest.status.in_(live),
            )
            .order_by(ApprovalRequest.created_at.desc())
        ).first()

    def get(self, approval_id: str, *, tenant_id: str) -> ApprovalRequest:
        """Return an approval, enforcing tenant isolation."""

        row = self._session.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.tenant_id == tenant_id,
            )
        ).first()
        if row is None:
            raise ApprovalNotFound("Approval request not found.")
        self._expire_if_needed(row)
        return row

    def list(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        agent_type: str | None = None,
        limit: int = 50,
    ) -> list[ApprovalRequest]:
        """List approvals for one tenant, newest first."""

        stmt = select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        if agent_type:
            stmt = stmt.where(ApprovalRequest.agent_type == agent_type)
        rows = self._session.scalars(
            stmt.order_by(ApprovalRequest.created_at.desc()).limit(min(limit, 200))
        ).all()
        return list(rows)

    # ── Review ────────────────────────────────────────────────────────────

    def approve(
        self, approval_id: str, *, tenant_id: str, reviewer_id: str
    ) -> ApprovalRequest:
        """Approve a pending request. An expired request cannot be approved."""

        row = self._transition(
            approval_id,
            tenant_id=tenant_id,
            from_status=ApprovalStatus.PENDING.value,
            to_status=ApprovalStatus.APPROVED.value,
            reviewer_id=reviewer_id,
            event=AuditAction.APPROVAL_APPROVED,
        )
        return row

    def reject(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        reviewer_id: str,
        comment: str | None = None,
    ) -> ApprovalRequest:
        """Reject a pending request, stopping the paused action."""

        row = self._transition(
            approval_id,
            tenant_id=tenant_id,
            from_status=ApprovalStatus.PENDING.value,
            to_status=ApprovalStatus.REJECTED.value,
            reviewer_id=reviewer_id,
            comment=comment,
            event=AuditAction.APPROVAL_REJECTED,
        )
        return row

    def cancel(
        self, approval_id: str, *, tenant_id: str, actor_id: str
    ) -> ApprovalRequest:
        """Cancel a request that is still pending."""

        return self._transition(
            approval_id,
            tenant_id=tenant_id,
            from_status=ApprovalStatus.PENDING.value,
            to_status=ApprovalStatus.CANCELLED.value,
            reviewer_id=actor_id,
            event=AuditAction.APPROVAL_CANCELLED,
        )

    def _transition(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        from_status: str,
        to_status: str,
        reviewer_id: str,
        comment: str | None = None,
        event: AuditAction,
    ) -> ApprovalRequest:
        """Atomically move an approval between states."""

        row = self.get(approval_id, tenant_id=tenant_id)
        if row.status == to_status:
            # Already in the target state: treat as a no-op rather than an error
            # so a retried request is not reported as a conflict.
            return row
        if row.status != from_status:
            if row.status == ApprovalStatus.EXPIRED.value:
                raise ApprovalExpired("This approval request has expired.")
            raise ApprovalConflict(
                f"Approval is '{row.status}' and cannot move to '{to_status}'."
            )
        if _is_expired(row, now=datetime.now(UTC)):
            row.status = ApprovalStatus.EXPIRED.value
            self._session.commit()
            raise ApprovalExpired("This approval request has expired.")

        row.status = to_status
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(UTC)
        if comment is not None:
            row.review_comment = comment[:2000]
        self._session.commit()
        self._session.refresh(row)

        log_agent_event(
            self._session,
            tenant_id=tenant_id,
            action=event,
            resource_type="approval_request",
            resource_id=row.id,
            actor_user_id=reviewer_id,
            metadata={
                "agent_type": row.agent_type,
                "conversation_id": row.conversation_id,
                "action_type": row.action_type,
                "result_status": to_status,
            },
        )
        return row

    # ── Execution (idempotent) ────────────────────────────────────────────

    def claim_for_execution(
        self, approval_id: str, *, tenant_id: str
    ) -> ApprovalRequest:
        """Atomically claim an approved request for execution.

        Returns the claimed row. Raises :class:`ApprovalConflict` when another
        caller already claimed or executed it.
        """

        now = datetime.now(UTC)
        result = self._session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == ApprovalStatus.APPROVED.value,
            )
            .values(status=ApprovalStatus.EXECUTING.value, updated_at=now)
        )
        if result.rowcount == 0:
            # The conditional UPDATE matched nothing; the session is still usable,
            # so re-read the row to report the real status. Rolling back here
            # would discard unrelated pending work owned by the caller's session.
            row = self.get(approval_id, tenant_id=tenant_id)
            raise ApprovalConflict(
                f"Approval '{approval_id}' is '{row.status}' and was already "
                "claimed or executed."
            )
        self._session.commit()
        return self.get(approval_id, tenant_id=tenant_id)

    def complete_execution(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        outcome: dict[str, Any],
        succeeded: bool,
    ) -> ApprovalRequest:
        """Record the terminal result of an executed action."""

        status = (
            ApprovalStatus.EXECUTED.value if succeeded else ApprovalStatus.FAILED.value
        )
        self._session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == ApprovalStatus.EXECUTING.value,
            )
            .values(
                status=status,
                execution_result=outcome,
                updated_at=datetime.now(UTC),
            )
        )
        self._session.commit()
        row = self.get(approval_id, tenant_id=tenant_id)

        log_agent_event(
            self._session,
            tenant_id=tenant_id,
            action=(
                AuditAction.AGENT_ACTION_EXECUTED
                if succeeded
                else AuditAction.AGENT_ACTION_FAILED
            ),
            resource_type="approval_request",
            resource_id=row.id,
            actor_user_id=None,
            metadata={
                "agent_type": row.agent_type,
                "conversation_id": row.conversation_id,
                "action_type": row.action_type,
                "result_status": status,
            },
        )
        return row

    def mark_executed(
        self, approval_id: str, *, tenant_id: str, outcome: dict[str, Any]
    ) -> ApprovalRequest:
        """Convenience wrapper for a successful execution."""

        return self.complete_execution(
            approval_id, tenant_id=tenant_id, outcome=outcome, succeeded=True
        )

    # ── Expiration ────────────────────────────────────────────────────────

    def expire_if_due(self, approval_id: str, *, tenant_id: str) -> ApprovalRequest:
        """Expire a request whose window has closed. Safe to call repeatedly."""

        row = self.get(approval_id, tenant_id=tenant_id)
        return row

    def _expire_if_needed(self, row: ApprovalRequest) -> None:
        """Mark a pending row EXPIRED when read after its deadline."""

        if row.status == ApprovalStatus.PENDING.value and _is_expired(
            row, now=datetime.now(UTC)
        ):
            row.status = ApprovalStatus.EXPIRED.value
            self._session.commit()
            log_agent_event(
                self._session,
                tenant_id=row.tenant_id,
                action=AuditAction.APPROVAL_EXPIRED,
                resource_type="approval_request",
                resource_id=row.id,
                metadata={
                    "agent_type": row.agent_type,
                    "conversation_id": row.conversation_id,
                    "action_type": row.action_type,
                },
            )


def execute_once(
    service: ApprovalService,
    approval_id: str,
    *,
    tenant_id: str,
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run *action* at most once, guarded by a single atomic claim.

    Returns a payload describing the outcome; never raises for a duplicate
    attempt, so a retried resume is a no-op rather than a failure.
    """

    try:
        claimed = service.claim_for_execution(approval_id, tenant_id=tenant_id)
    except ApprovalConflict:
        row = service.get(approval_id, tenant_id=tenant_id)
        return {
            "executed": False,
            "duplicate": True,
            "status": row.status,
            "result": row.execution_result,
        }

    try:
        outcome = action()
    except Exception as error:  # noqa: BLE001 - recorded as a failed execution
        service.complete_execution(
            claimed.id,
            tenant_id=tenant_id,
            outcome={"error": type(error).__name__},
            succeeded=False,
        )
        raise

    service.mark_executed(claimed.id, tenant_id=tenant_id, outcome=outcome)
    return {
        "executed": True,
        "duplicate": False,
        "status": ApprovalStatus.EXECUTED.value,
        "result": outcome,
    }
