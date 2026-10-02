"""LangGraph orchestration for the Day 7 multi-agent workflow.

Graph shape::

    START
      ↓
    supervisor_start
      ↓
    triage
      ↓
    route_after_triage  (conditional edges)
      ├── support  ─┐
      ├── job      ─┤
      ├── invoice  ─┼→ supervisor_review
      └── human    ─┘         ↓
                     decide_after_review (conditional)
                       ├── finish
                       └── escalate → human → supervisor_review

``conversation_id`` is the LangGraph ``thread_id`` exactly as in Day 6, so the
whole multi-agent state is checkpointed and survives restarts.
"""

from __future__ import annotations

import contextvars
from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agent.checkpointer import (
    CheckpointStateError,
    CheckpointUnavailableError,
    is_checkpoint_failure,
)
from agents.context import AgentContext
from agents.decisions import AgentDestination, AgentResult
from agents.specialists import (
    HumanEscalationAgent,
    InvoiceAgent,
    JobAgent,
    SupportAgent,
)
from agents.state import MultiAgentState
from agents.supervisor import NEXT_ESCALATE, NEXT_FINISH, SupervisorAgent
from agents.tools.base import HUMAN, INVOICE, JOB, SUPPORT
from agents.triage import TriageAgent

#: Recursion ceiling applied to ``graph.invoke`` as a hard backstop.
GRAPH_RECURSION_LIMIT = 24

#: Per-request context binding. A ``ContextVar`` (rather than instance state)
#: keeps concurrent requests isolated, and the trusted context is deliberately
#: never written into the checkpointed graph state.
_CONTEXT: contextvars.ContextVar[AgentContext | None] = contextvars.ContextVar(
    "multi_agent_context", default=None
)


def _extract_pending_approval(result: Any) -> dict[str, Any]:
    """Strip LangGraph's ``__interrupt__`` marker and expose a stable field.

    The installed LangGraph version suspends the run and returns the partial
    state with ``__interrupt__`` instead of raising, so the pause has to be
    detected from the returned payload.
    """

    if not isinstance(result, dict):
        return result
    pending = result.pop("__interrupt__", None)
    if not pending:
        return result
    first = pending[0] if isinstance(pending, list | tuple) else pending
    value = getattr(first, "value", first)
    if not isinstance(value, dict):
        value = {}
    return {**result, "pending_approval": value}


def _agent_result_to_state(result: AgentResult) -> dict[str, Any]:
    """Serialize a specialist's :class:`AgentResult` into graph state.

    Identifier fields resolved by the specialist (for example the job ID it just
    created) are lifted into top-level state so later nodes and the supervisor
    can reference them directly.
    """

    updates: dict[str, Any] = {
        "agent_result": result.model_dump(),
        "requires_human": result.requires_human,
    }
    if result.requires_human and result.reason:
        updates["human_reason"] = result.reason
    if result.agent == HUMAN and result.requires_human:
        # The handover summary now exists; the supervisor must finish rather
        # than route back to the human agent.
        updates["human_handover_done"] = True

    data = result.data or {}
    if data.get("job_id") and not result.requires_human:
        updates["job_id"] = data["job_id"]
    if data.get("invoice_id") and not result.requires_human:
        updates["invoice_id"] = data["invoice_id"]
    if data.get("proposed_action"):
        # Day 9: a proposed action is handed to the approval gate, not executed.
        updates["proposed_action"] = data["proposed_action"]
    return updates


class MultiAgentWorkflow:
    """Compiled multi-agent LangGraph plus its node implementations."""

    def __init__(
        self,
        *,
        supervisor: SupervisorAgent,
        triage: TriageAgent,
        support: SupportAgent,
        job: JobAgent,
        invoice: InvoiceAgent,
        human: HumanEscalationAgent,
        approval_gate: Any | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.supervisor = supervisor
        self.triage = triage
        self.support = support
        self.job = job
        self.invoice = invoice
        self.human = human
        self.approval_gate = approval_gate
        self.graph = self._build(checkpointer)

    # ── Graph construction ────────────────────────────────────────────────

    def _build(self, checkpointer: Any | None) -> Any:
        graph = StateGraph(MultiAgentState)

        graph.add_node("supervisor_start", self._node(self.supervisor.start))
        graph.add_node("triage", self._node(self.triage.run))
        graph.add_node(SUPPORT, self._node(self.support.run))
        graph.add_node(JOB, self._node(self.job.run))
        graph.add_node(INVOICE, self._node(self.invoice.run))
        graph.add_node(HUMAN, self._node(self.human.run))
        graph.add_node("supervisor_review", self._node(self.supervisor.review))
        # Day 9: the approval gate sits between a specialist's proposal and the
        # supervisor, and is the only place a LangGraph interrupt is raised.
        if self.approval_gate is not None:
            graph.add_node("approval_gate", self._node(self.approval_gate))

        graph.add_edge(START, "supervisor_start")
        graph.add_edge("supervisor_start", "triage")

        graph.add_conditional_edges(
            "triage",
            self._route_after_triage,
            {
                SUPPORT: SUPPORT,
                JOB: JOB,
                INVOICE: INVOICE,
                HUMAN: HUMAN,
            },
        )

        after_specialist = (
            "approval_gate" if self.approval_gate is not None else "supervisor_review"
        )
        for specialist in (SUPPORT, JOB, INVOICE):
            # With a gate installed every specialist flows through it, so a
            # proposed action is always policy-checked before execution.
            graph.add_edge(specialist, after_specialist)
        if self.approval_gate is not None:
            graph.add_edge("approval_gate", "supervisor_review")

        graph.add_conditional_edges(
            "supervisor_review",
            self.supervisor.next_step,
            {NEXT_FINISH: END, NEXT_ESCALATE: HUMAN},
        )
        graph.add_edge(HUMAN, "supervisor_review")

        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _node(handler: Any) -> Any:
        """Adapt an agent ``run``/``start``/``review`` callable to a graph node.

        Two responsibilities:

        1. Every node needs the trusted :class:`AgentContext`, which is
           per-request and therefore cannot live in the persisted graph state.
           It is attached to the invocation via a :class:`ContextVar` set in
           :meth:`invoke`.
        2. Specialized agents return a typed :class:`AgentResult`; this is the
           boundary that serializes it into checkpointable graph state.
        """

        def _wrapped(state: MultiAgentState) -> dict[str, Any]:
            ctx = _CONTEXT.get()
            if ctx is None:
                raise RuntimeError("agent context is not bound to this invocation")
            outcome = handler(state, ctx)
            if isinstance(outcome, AgentResult):
                return _agent_result_to_state(outcome)
            return outcome

        return _wrapped

    @staticmethod
    def _route_after_triage(state: MultiAgentState) -> str:
        destination = state.get("destination")
        try:
            return AgentDestination(destination).value
        except (TypeError, ValueError):
            return AgentDestination.SUPPORT.value

    @staticmethod
    def _wrap_errors(call: Any, ctx: AgentContext) -> Any:
        """Run a graph call, translating checkpoint failures into typed errors."""

        token = _CONTEXT.set(ctx)
        try:
            return call()
        except (CheckpointUnavailableError, CheckpointStateError, GraphInterrupt):
            # A pending human approval is an expected outcome, not a failure.
            raise
        except Exception as exc:  # noqa: BLE001
            if is_checkpoint_failure(exc):
                raise CheckpointUnavailableError(
                    "Unable to read or write persistent conversation state."
                ) from exc
            raise
        finally:
            _CONTEXT.reset(token)

    # ── Invocation ────────────────────────────────────────────────────────

    def invoke(self, state: MultiAgentState, ctx: AgentContext) -> dict[str, Any]:
        """Run the workflow for one customer turn.

        ``conversation_id`` is used verbatim as the LangGraph ``thread_id``.

        When the Day 9 approval gate pauses the turn, the installed LangGraph
        version returns the partial state carrying a ``__interrupt__`` entry
        rather than raising. That entry is removed and re-exposed as
        ``pending_approval`` so callers see a stable shape; the graph itself
        stays suspended on the same thread until :meth:`resume` is called.
        """

        initial: MultiAgentState = {
            "conversation_id": ctx.conversation_id,
            "customer_id": ctx.customer_id,
            "user_message": state.get("user_message", ""),
        }
        config = {"configurable": {"thread_id": ctx.conversation_id}}
        result = self._wrap_errors(
            lambda: self.graph.invoke(
                initial, config=config, recursion_limit=GRAPH_RECURSION_LIMIT
            ),
            ctx,
        )
        return _extract_pending_approval(result)

    def resume(self, ctx: AgentContext, decision: dict[str, Any]) -> dict[str, Any]:
        """Resume a paused thread with a human decision.

        The same ``thread_id`` (the conversation id) is reused, so the graph
        continues from its checkpointed state instead of starting a new run.
        """

        config = {"configurable": {"thread_id": ctx.conversation_id}}
        return self._wrap_errors(
            lambda: self.graph.invoke(
                Command(resume=decision),
                config=config,
                recursion_limit=GRAPH_RECURSION_LIMIT,
            ),
            ctx,
        )

    def pending_state(self, ctx: AgentContext) -> Any:
        """Return the LangGraph snapshot for a conversation, if any."""

        config = {"configurable": {"thread_id": ctx.conversation_id}}
        token = _CONTEXT.set(ctx)
        try:
            return self.graph.get_state(config)
        finally:
            _CONTEXT.reset(token)
