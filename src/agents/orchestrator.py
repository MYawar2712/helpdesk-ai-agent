"""Day 7 multi-agent orchestrator.

Exposes a single ``invoke`` entry point compatible with the Day 5/6
:class:`~agent.graph.HelpdeskAgent` contract so the existing chat endpoint can
drive the multi-agent workflow without changing its call site.

When a request carries no authenticated customer (the legacy unauthenticated
``/chat`` endpoint), the orchestrator delegates to the wrapped Day 6 agent so
existing behaviour is preserved rather than regressed.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.config import AgentConfigService
from agents.context import AgentContext
from agents.decisions import AgentDestination
from agents.graph import MultiAgentWorkflow
from agents.specialists import (
    HumanEscalationAgent,
    InvoiceAgent,
    JobAgent,
    SupportAgent,
)
from agents.state import MultiAgentState
from agents.supervisor import DEFAULT_MAX_ITERATIONS, SupervisorAgent
from agents.tools import KnowledgeRetriever, ToolRegistry, build_tool_registry
from agents.triage import TriageAgent
from hitl.graph_gate import PENDING_MESSAGE as PENDING_APPROVAL_MESSAGE

logger = logging.getLogger(__name__)


class MultiAgentHelpdesk:
    """Supervisor-driven multi-agent facade for the customer chat surface."""

    def __init__(
        self,
        *,
        workflow: MultiAgentWorkflow,
        tools: ToolRegistry,
        fallback: Any | None = None,
        config_service_factory: Any | None = None,
    ) -> None:
        self.workflow = workflow
        self.tools = tools
        self._fallback = fallback
        #: Callable returning a fresh Day 8 config service for one turn.
        self._config_service_factory = config_service_factory

    # ── Construction ──────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        repository: Any,
        llm: Any | None = None,
        checkpointer: Any | None = None,
        retriever: KnowledgeRetriever | None = None,
        fallback: Any | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        use_llm_triage: bool = True,
        config_service: AgentConfigService | None = None,
        config_service_factory: Any | None = None,
        tenant_retriever: Any | None = None,
        approval_gate: Any | None = None,
    ) -> MultiAgentHelpdesk:
        """Assemble the supervisor, triage, specialists, and tool registry.

        Args:
            config_service: Day 8 tenant configuration loader. When omitted,
                agents fall back to safe platform defaults.
            tenant_retriever: Day 8 tenant-isolated retriever used by Support.
        """

        tools = build_tool_registry(repository, retriever=retriever)
        supervisor = SupervisorAgent(
            llm=llm,
            max_iterations=max_iterations,
            config_service=config_service,
        )
        workflow = MultiAgentWorkflow(
            supervisor=supervisor,
            triage=TriageAgent(
                tools=tools,
                llm=llm,
                use_llm=use_llm_triage,
                config_service=config_service,
            ),
            support=SupportAgent(
                tools=tools,
                llm=llm,
                config_service=config_service,
                tenant_retriever=tenant_retriever,
                platform_retriever=retriever,
            ),
            job=JobAgent(tools=tools, llm=llm, config_service=config_service),
            invoice=InvoiceAgent(tools=tools, llm=llm, config_service=config_service),
            human=HumanEscalationAgent(
                tools=tools, llm=llm, config_service=config_service
            ),
            approval_gate=approval_gate,
            checkpointer=checkpointer,
        )
        return cls(
            workflow=workflow,
            tools=tools,
            fallback=fallback,
            config_service_factory=config_service_factory,
        )

    # ── Invocation ────────────────────────────────────────────────────────

    def invoke(
        self,
        ticket_text: str,
        *,
        email_thread_id: str | None = None,
        email_message_id: str | None = None,
        customer_id: str | None = None,
        sender_email: str = "",
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one customer turn through the multi-agent workflow.

        Args:
            ticket_text: The customer's message.
            email_thread_id: Conversation id, used verbatim as ``thread_id``.
            email_message_id: Unused by the workflow; accepted for Day 5 parity.
            customer_id: Authenticated customer. Required for the multi-agent path.
            sender_email: Customer email, when known.
            tenant_id: Authenticated tenant, when the deployment is multi-tenant.

        Returns:
            A state mapping containing at least ``final_response``, mirroring the
            shape the chat endpoint already consumes.
        """

        if not customer_id:
            # No authenticated identity: keep the pre-Day-7 behaviour rather than
            # running a workflow that could not enforce ownership.
            if self._fallback is not None:
                return self._fallback.invoke(
                    ticket_text,
                    email_thread_id=email_thread_id,
                    email_message_id=email_message_id,
                    customer_id=customer_id,
                    sender_email=sender_email,
                )
            raise ValueError("customer_id is required for the multi-agent workflow")

        conversation_id = email_thread_id or customer_id
        ctx = self._build_context(
            conversation_id=conversation_id,
            customer_id=customer_id,
            tenant_id=tenant_id,
        )
        initial: MultiAgentState = {"user_message": ticket_text}
        try:
            result = self.workflow.invoke(initial, ctx)
        finally:
            # Per-turn configuration holds a short-lived database session; it is
            # released here so concurrent conversations cannot exhaust the pool.
            self._release_context(ctx)
        return self._to_public_state(result)

    def resume(
        self,
        *,
        conversation_id: str,
        customer_id: str,
        decision: dict[str, Any],
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Resume a paused conversation with a human approval decision.

        Reuses the same ``thread_id`` as the original turn, so LangGraph
        continues the checkpointed run rather than starting a new one.
        """

        ctx = self._build_context(
            conversation_id=conversation_id,
            customer_id=customer_id,
            tenant_id=tenant_id,
        )
        try:
            state = self.workflow.resume(ctx, decision)
        finally:
            self._release_context(ctx)
        return self._to_public_state(state)

    def pending_snapshot(
        self, *, conversation_id: str, customer_id: str, tenant_id: str | None = None
    ) -> Any:
        """Return the LangGraph snapshot for a conversation awaiting review."""

        ctx = self._build_context(
            conversation_id=conversation_id,
            customer_id=customer_id,
            tenant_id=tenant_id,
        )
        try:
            return self.workflow.pending_state(ctx)
        finally:
            self._release_context(ctx)

    @staticmethod
    def _release_context(ctx: AgentContext) -> None:
        """Release per-turn resources held by a request context.

        Failures here are never allowed to mask the turn's own outcome, so the
        release is best-effort.
        """

        service = ctx.config_service
        closer = getattr(service, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001 - cleanup must not break the turn
                logger.warning("Failed to release per-turn configuration resources")

    def _build_context(
        self, *, conversation_id: str, customer_id: str, tenant_id: str | None
    ) -> AgentContext:
        """Build a trusted context for this request."""

        return AgentContext(
            customer_id=customer_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            tenant_scoped=tenant_id is not None,
            config_service=(
                self._config_service_factory()
                if self._config_service_factory is not None
                else None
            ),
            tool_registry=self.tools,
        )

    @staticmethod
    def _to_public_state(state: MultiAgentState) -> dict[str, Any]:
        """Normalise graph state into the legacy agent-state contract."""

        agent_result = state.get("agent_result") or {}
        destination = state.get("destination") or AgentDestination.SUPPORT.value
        pending = state.get("pending_approval")
        if pending:
            # Day 9: the turn is suspended awaiting a human decision. The
            # customer sees a neutral message with no internal detail.
            final = PENDING_APPROVAL_MESSAGE
        else:
            final = state.get("final_response") or agent_result.get("message") or ""
        return {
            "final_response": final,
            "response": final,
            "route": "handoff" if state.get("requires_human") else "respond",
            "intent": state.get("intent", ""),
            "predicted_category": state.get("category", ""),
            "predicted_priority": state.get("priority", ""),
            "ticket_id": state.get("ticket_id"),
            "customer_id": state.get("customer_id"),
            "thread_id": state.get("conversation_id"),
            "conversation_id": state.get("conversation_id"),
            "job_id": state.get("job_id"),
            "invoice_id": state.get("invoice_id"),
            "destination": destination,
            "agent": agent_result.get("agent"),
            "agent_result": agent_result,
            "requires_human": bool(state.get("requires_human")),
            "human_reason": state.get("human_reason"),
            "iteration": state.get("iteration", 0),
            "pending_approval": pending,
            "approval_id": (pending or {}).get("approval_id"),
        }


__all__ = ["MultiAgentHelpdesk", "MultiAgentState"]
