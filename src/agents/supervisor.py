"""Supervisor Agent for the Day 7 multi-agent workflow.

The supervisor starts the workflow, maintains overall state, delegates to
triage, receives structured results from the specialized agents, decides whether
another agent should run, and composes the final customer-facing response.

It is the only node that writes ``final_response``.
"""

from __future__ import annotations

from typing import Any, Protocol

from agents.config import AgentConfigService, AgentType, build_agent_system_prompt
from agents.context import AgentContext
from agents.prompts import SUPERVISOR_INSTRUCTIONS
from agents.state import MultiAgentState

#: Default ceiling on supervisor/specialist round trips per customer turn.
DEFAULT_MAX_ITERATIONS = 4

#: Outcome codes produced by :meth:`SupervisorAgent.review`.
NEXT_FINISH = "finish"
NEXT_ESCALATE = "escalate"


class SupervisorLLM(Protocol):
    """LLM surface required by the supervisor (mockable in tests)."""

    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class SupervisorAgent:
    """Owns workflow progression and the customer-facing response."""

    name = "supervisor"
    agent_type = AgentType.SUPERVISOR

    def __init__(
        self,
        *,
        llm: SupervisorLLM | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        config_service: AgentConfigService | None = None,
    ) -> None:
        self._llm = llm
        self._max_iterations = max(1, max_iterations)
        self._config_service = config_service

    @property
    def max_iterations(self) -> int:
        return self._max_iterations

    # ── Node 1: start ─────────────────────────────────────────────────────

    def start(self, state: MultiAgentState, ctx: AgentContext) -> dict[str, Any]:
        """Initialize the workflow state for a new turn.

        Validates that the trusted context is present before any agent runs, so
        an unidentified request can never reach a business tool.
        """

        if not ctx.customer_id:
            raise ValueError("supervisor requires an authenticated customer context")

        message = state.get("user_message", "").strip()
        return {
            "conversation_id": ctx.conversation_id,
            "tenant_id": ctx.tenant_id,
            "customer_id": ctx.customer_id,
            "iteration": 0,
            "max_iterations": self._max_iterations,
            "visited_agents": [],
            "requires_human": False,
            "human_reason": None,
            "human_handover_done": False,
            "agent_result": None,
            "final_response": "",
            "tool_calls": [],
            "messages": [
                {
                    "role": "user",
                    "content": message,
                    "conversation_id": ctx.conversation_id,
                }
            ],
        }

    # ── Node 2: review the specialist result ──────────────────────────────

    def review(self, state: MultiAgentState, ctx: AgentContext) -> dict[str, Any]:
        """Decide the next step after a specialized agent has run.

        Returns the routing keys the conditional edge consumes. The workflow
        always terminates: either the turn is finished, or it is escalated to a
        human. This is what prevents a
        ``supervisor -> triage -> agent -> supervisor`` loop from spinning.
        """

        iteration = int(state.get("iteration", 0)) + 1
        result = state.get("agent_result") or {}
        visited = list(state.get("visited_agents") or [])
        if result.get("agent"):
            visited.append(str(result["agent"]))

        updates: dict[str, Any] = {"iteration": iteration, "visited_agents": visited}

        # A specialist explicitly asking for a human always wins.
        if result.get("requires_human") or state.get("requires_human"):
            reason = (
                result.get("reason")
                or state.get("human_reason")
                or ("The request needs a human support specialist.")
            )
            updates.update(
                {
                    "requires_human": True,
                    "human_reason": reason,
                    "final_response": self.compose(state, ctx, escalated=True),
                }
            )
            return updates

        # Loop guard: the workflow budget is exhausted.
        if iteration >= int(state.get("max_iterations", self._max_iterations)):
            reason = "The request could not be completed within the allowed steps."
            updates.update(
                {
                    "requires_human": True,
                    "human_reason": reason,
                    "final_response": self.compose(state, ctx, escalated=True),
                }
            )
            return updates

        # Normal completion.
        updates["final_response"] = self.compose(state, ctx, escalated=False)
        return updates

    def next_step(self, state: MultiAgentState) -> str:
        """Return the conditional-edge destination after :meth:`review`.

        ``escalate`` is returned at most once per turn: once the human handover
        agent has produced its summary the workflow finishes. That is what stops
        a ``supervisor -> human -> supervisor -> human`` cycle from looping.
        """

        if not state.get("requires_human"):
            return NEXT_FINISH
        if state.get("human_handover_done"):
            return NEXT_FINISH
        return NEXT_ESCALATE

    # ── Final response ────────────────────────────────────────────────────

    def compose(
        self, state: MultiAgentState, ctx: AgentContext, *, escalated: bool
    ) -> str:
        """Build the customer-facing reply from the structured agent result."""

        result = state.get("agent_result") or {}
        message = (result.get("message") or "").strip()
        if not message:
            message = (
                "I've passed this to a human support specialist who will follow up."
                if escalated
                else "I've noted your request. Could you share a little more detail?"
            )

        if self._llm is None or escalated:
            return message

        prompt = (
            f"Customer message:\n{state.get('user_message', '')}\n\n"
            f"Verified internal outcome:\n{message}\n\n"
            f"Ticket: {state.get('ticket_id') or 'none'}\n"
            f"Job: {state.get('job_id') or 'none'}\n"
            f"Invoice: {state.get('invoice_id') or 'none'}\n\n"
            "Rewrite this as a short, friendly reply to the customer. "
            "Do not invent any detail that is not present above."
        )
        system_prompt = build_agent_system_prompt(
            config=self._config(ctx),
            platform_agent_rules=SUPERVISOR_INSTRUCTIONS,
        )
        try:
            composed = self._llm.generate(system_prompt, prompt).strip()
            return composed or message
        except Exception:  # noqa: BLE001 - never fail a turn over phrasing
            return message

    def _config(self, ctx: AgentContext) -> Any:
        """Load supervisor tenant configuration when a service is available."""

        from agents.config import AgentConfig

        service = ctx.config_service or self._config_service
        if service is None:
            return AgentConfig(tenant_id=ctx.tenant_id, agent_type=self.agent_type)
        return service.get(ctx.tenant_id, self.agent_type)

    def mark_handled_by(self, state: MultiAgentState) -> str:
        """Return the ``handled_by`` value to persist on the ticket."""

        return "HUMAN" if state.get("requires_human") else "AI_AGENT"
