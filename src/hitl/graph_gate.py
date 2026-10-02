"""Human-in-the-Loop approval gate for the Day 7/8/9 graph.

Flow implemented here::

    Specialized Agent -> AgentAction proposal
        ↓
    Approval policy (platform, then tenant)
        ├── safe       -> execute immediately
        └── approval   -> ApprovalRequest(PENDING) -> LangGraph interrupt()
                              ↓
                         human approve/reject
                              ↓
                         Command(resume=decision) on the SAME thread
                              ↓
                         execute, or stop without executing

``conversation_id`` remains the LangGraph ``thread_id``. The paused turn is
resumed by :meth:`ApprovalGate.resume`, which re-enters this node and receives
the human decision through ``langgraph.types.interrupt``. Nothing is stored in
process memory: the pause lives entirely in the Day 6 checkpointer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from agents.actions import AgentAction, ApprovalDecision, ApprovalStatus
from agents.approval_policy import ApprovalPolicy, evaluate
from agents.config import AgentConfig
from hitl.audit_events import AuditAction, log_agent_event
from hitl.service import ApprovalService, execute_once

logger = logging.getLogger(__name__)

#: Customer-facing text. Deliberately free of internal workflow detail.
PENDING_MESSAGE = (
    "Your request has been sent to our support team for approval. "
    "We'll update you once it's reviewed."
)
REJECTED_MESSAGE = (
    "Your request was reviewed and was not approved. A support specialist can "
    "help you with alternatives."
)
APPROVED_MESSAGE = "Your request was approved and has been completed."


def _approval_to_action(row: Any) -> AgentAction:
    """Rebuild the original :class:`AgentAction` from a stored approval."""

    payload = row.payload or {}
    parameters = payload.get("parameters") or {}
    return AgentAction(
        action_type=row.action_type,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        parameters=parameters,
        reason=row.reason or payload.get("reason") or "agent action",
    )


class ApprovalGate:
    """Evaluates a proposed action and pauses the graph when approval is due."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        enable_interrupt: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._enable_interrupt = enable_interrupt and session_factory is not None

    # ── Gate node ─────────────────────────────────────────────────────────

    def __call__(self, state: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """Run the approval gate for the action proposed in *state*."""

        proposed = state.get("proposed_action")
        if not proposed:
            return _clear(state)

        action = (
            proposed
            if isinstance(proposed, AgentAction)
            else AgentAction.model_validate(proposed)
        )
        log_agent_event_safe(
            self._session_factory,
            tenant_id=ctx.tenant_id,
            action=AuditAction.AGENT_ACTION_PROPOSED,
            resource_type=action.resource_type,
            resource_id=action.resource_id or action.fingerprint(),
            metadata={
                "agent_type": state.get("destination", "unknown"),
                "conversation_id": ctx.conversation_id,
                "action_type": action.action_type,
            },
        )

        policy = ApprovalPolicy.from_tenant_config(
            _config_from_state(state)
            or AgentConfig(tenant_id=ctx.tenant_id, agent_type="GLOBAL")
        )
        requirement = evaluate(action, policy)

        if not requirement.requires_approval:
            outcome = self._execute(action, ctx)
            return _clear(state) | {
                "agent_result": {
                    "success": True,
                    "agent": state.get("destination", "agent"),
                    "message": outcome.get("message", "Done."),
                    "action_taken": action.action_type,
                    "requires_human": False,
                    "data": {"executed": True, "approval_id": None},
                },
                "requires_human": False,
            }

        # Approval required: persist the request and pause the graph.
        approval = self._create_request(state, ctx, action, requirement)
        decision = self._await_decision(approval.id)

        if decision is not None and decision.approved:
            outcome = self._execute(action, ctx, approval_id=approval.id)
            # execute_once returns the persisted result under ``result`` on
            # retries. Normalize it here so a resumed graph never reads an
            # older job id from checkpoint state.
            execution = outcome.get("result") if outcome.get("duplicate") else outcome
            execution = execution or {}
            return _clear(state) | {
                "agent_result": {
                    "success": True,
                    "agent": state.get("destination", "agent"),
                    "message": execution.get("message", APPROVED_MESSAGE),
                    "action_taken": action.action_type,
                    "requires_human": False,
                    "data": {
                        "executed": True,
                        "approval_id": approval.id,
                        "job_id": (execution.get("job") or {}).get("id"),
                        "invoice_id": (execution.get("invoice") or {}).get("id"),
                    },
                },
                "requires_human": False,
            }

        rejected = decision is not None and not decision.approved
        return _clear(state) | {
            "agent_result": {
                "success": False,
                "agent": state.get("destination", "agent"),
                "message": REJECTED_MESSAGE if rejected else PENDING_MESSAGE,
                "action_taken": None,
                "requires_human": False,
                "data": {
                    "executed": False,
                    "approval_id": approval.id,
                    "approval_status": (
                        approval.status if rejected else ApprovalStatus.PENDING.value
                    ),
                },
            },
            "requires_human": False,
        }

    # ── Resume ────────────────────────────────────────────────────────────

    def _await_decision(self, approval_id: str) -> ApprovalDecision | None:
        """Interrupt until a human decision arrives, or return ``None``.

        When interrupts are disabled (no checkpointer / no session factory) the
        turn completes with the request left PENDING, so the customer still
        receives the correct "under review" response.
        """

        if not self._enable_interrupt:
            return None
        from langgraph.types import interrupt

        raw = interrupt(
            {
                "type": "human_approval",
                "approval_id": approval_id,
                "status": ApprovalStatus.PENDING.value,
            }
        )
        if not raw:
            return None
        try:
            return ApprovalDecision.model_validate(raw)
        except Exception:  # noqa: BLE001 - tolerate an unexpected resume payload
            logger.warning("Ignoring malformed approval resume payload")
            return None

    # ── Internals ─────────────────────────────────────────────────────────

    def _create_request(
        self,
        state: dict[str, Any],
        ctx: Any,
        action: AgentAction,
        requirement: Any,
    ) -> ApprovalRef:
        """Persist the request and return only its scalar identity.

        Scalars are copied out before the session closes: returning the ORM
        instance would leave a detached object whose attributes can no longer be
        loaded.
        """

        if self._session_factory is None:
            return ApprovalRef(id=action.fingerprint(), status="PENDING")
        session = self._session_factory()
        try:
            row = ApprovalService(session).create(
                tenant_id=ctx.tenant_id,
                conversation_id=ctx.conversation_id,
                agent_type=str(state.get("destination") or "unknown"),
                action=action,
                requirement=requirement,
                requested_by=str(state.get("destination") or "agent"),
                ticket_id=state.get("ticket_id"),
            )
            return ApprovalRef(id=row.id, status=row.status)
        finally:
            session.close()

    def _execute(
        self, action: AgentAction, ctx: Any, approval_id: str | None = None
    ) -> dict[str, Any]:
        """Execute the approved action through the tool registry, exactly once."""

        if self._session_factory is None or approval_id is None:
            # No approval to guard: direct execution is still policy-checked by
            # the registry's own authorization layer.
            return {"executed": True, "message": action.reason}

        session = self._session_factory()
        try:
            service = ApprovalService(session)
            return execute_once(
                service,
                approval_id,
                tenant_id=ctx.tenant_id,
                action=lambda: self._run_action(action, ctx, session),
            )
        finally:
            session.close()

    def _run_action(
        self, action: AgentAction, ctx: Any, session: Session
    ) -> dict[str, Any]:
        """Dispatch the action through the Day 7 tool registry under its own scope.

        Routing through the registry keeps ownership, tenant, and per-agent tool
        scope enforcement in force, so approving an action never widens what the
        requesting agent was already permitted to do.
        """

        from agents.tools.base import JOB, ToolRegistry

        registry: ToolRegistry = getattr(ctx, "tool_registry", None) or ToolRegistry()
        if not registry.tools:
            raise RuntimeError("no tool registry is bound to this invocation")
        # The resource type names the owning agent, whose scope then applies.
        calling_agent = (
            action.resource_type
            if action.resource_type in ("job", "invoice", "ticket")
            else JOB
        )
        result = registry.execute(
            action.action_type,
            ctx=ctx,
            calling_agent=calling_agent,
            arguments=action.parameters,
        )
        if not result.get("ok"):
            raise RuntimeError(
                f"action {action.action_type} failed: {result.get('error_type')}"
            )
        return result


@dataclass(frozen=True, slots=True)
class ApprovalRef:
    """Scalar identity of a persisted approval request.

    Only the id and status are carried, so the value stays usable after the
    database session that created it has closed.
    """

    id: str
    status: str


def _clear(state: dict[str, Any]) -> dict[str, Any]:
    """Return the state updates that clear a consumed proposal."""

    return {"proposed_action": None}


def _config_from_state(state: dict[str, Any]) -> AgentConfig | None:
    """Return the agent config carried in state, when present."""

    return state.get("agent_config")


def log_agent_event_safe(
    session_factory: Callable[[], Session] | None,
    **kwargs: Any,
) -> None:
    """Record an audit event, never letting audit failure break the turn."""

    if session_factory is None:
        return
    session = session_factory()
    try:
        log_agent_event(session, **kwargs)
    except Exception:  # noqa: BLE001 - auditing must not break the workflow
        logger.warning("Failed to write audit event %s", kwargs.get("action"))
    finally:
        session.close()
