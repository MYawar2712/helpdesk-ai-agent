"""Triage Agent: classify the request, pick a destination, and manage tickets.

Routing is decided by a deterministic classifier first, then optionally refined
by the LLM. Any LLM output must pass :func:`~agents.decisions.parse_routing_decision`
before it can influence control flow, so a malformed or hallucinated response
degrades to the deterministic decision instead of steering the workflow.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from agents.config import AgentConfigService, AgentType
from agents.context import AgentContext
from agents.decisions import (
    AgentDestination,
    RoutingDecision,
    TicketAction,
    parse_routing_decision,
)
from agents.prompts import ROUTING_SCHEMA_HINT, TRIAGE_INSTRUCTIONS
from agents.state import MultiAgentState
from agents.tools.base import TRIAGE, ToolRegistry
from models import TicketCategory, TicketIntent, normalize_ticket_category
from tools.classify_intent import classify_intent

#: Deterministic intent -> destination mapping.
_INTENT_DESTINATIONS: dict[TicketIntent, AgentDestination] = {
    TicketIntent.GENERAL_INQUIRY: AgentDestination.SUPPORT,
    TicketIntent.BILLING_INQUIRY: AgentDestination.INVOICE,
    TicketIntent.JOB_STATUS: AgentDestination.JOB,
    TicketIntent.CANCEL_JOB: AgentDestination.JOB,
    TicketIntent.RESCHEDULE_JOB: AgentDestination.JOB,
    TicketIntent.MODIFY_JOB: AgentDestination.JOB,
    TicketIntent.NEW_SERVICE_REQUEST: AgentDestination.JOB,
    TicketIntent.COMPLAINT: AgentDestination.SUPPORT,
    TicketIntent.TECHNICAL_SUPPORT: AgentDestination.SUPPORT,
    TicketIntent.HUMAN_ESCALATION: AgentDestination.HUMAN,
}

#: Deterministic intent -> canonical category mapping.
_INTENT_CATEGORIES: dict[TicketIntent, TicketCategory] = {
    TicketIntent.GENERAL_INQUIRY: TicketCategory.GENERAL,
    TicketIntent.BILLING_INQUIRY: TicketCategory.BILLING,
    TicketIntent.JOB_STATUS: TicketCategory.SCHEDULING,
    TicketIntent.CANCEL_JOB: TicketCategory.CANCELLATION,
    TicketIntent.RESCHEDULE_JOB: TicketCategory.SCHEDULING,
    TicketIntent.MODIFY_JOB: TicketCategory.SCHEDULING,
    TicketIntent.NEW_SERVICE_REQUEST: TicketCategory.TECHNICAL,
    TicketIntent.COMPLAINT: TicketCategory.GENERAL,
    TicketIntent.TECHNICAL_SUPPORT: TicketCategory.TECHNICAL,
    TicketIntent.HUMAN_ESCALATION: TicketCategory.GENERAL,
}

#: Financial disputes are never settled by an agent.
_DISPUTE_KEYWORDS = (
    "refund",
    "chargeback",
    "charged twice",
    "double charge",
    "double charged",
    "duplicate charge",
    "unauthorized charge",
    "overcharg",
    "wrong charge",
    "incorrect charge",
    "dispute",
    "fraud",
)

#: Immediate-danger signals that must reach a human.
_SAFETY_KEYWORDS = (
    "smoke",
    "spark",
    "burning smell",
    "exposed wiring",
    "gas leak",
    "flooding",
    "no heat",
    "no heating",
    "carbon monoxide",
    "danger",
    "emergency",
    "urgent safety",
)

# Identifier patterns. The hyphenated form is tried first because customers
# commonly write "job job-123", where one loose pattern would capture the
# literal word "job" as the identifier. The captured group accepts a run of
# digits (short ids like ``job-6``) or a 3+ character token, so an ordinary
# word such as "is" is never mistaken for an id.
_ID = r"(?:\d+|[a-z0-9]{3,})"
_JOB_PREFIXED_RE = re.compile(rf"\bjob-({_ID})\b", re.IGNORECASE)
_JOB_SPACED_RE = re.compile(rf"\bjob\s+({_ID})\b", re.IGNORECASE)
_INVOICE_PREFIXED_RE = re.compile(rf"\binvoice-({_ID})\b", re.IGNORECASE)
_INVOICE_SPACED_RE = re.compile(rf"\binvoice\s+({_ID})\b", re.IGNORECASE)

#: Words that can follow "job"/"invoice" but are never an identifier.
_NON_IDENTIFIERS = frozenset(
    {
        "id",
        "status",
        "number",
        "my",
        "the",
        "code",
        "ref",
        "job",
        "invoice",
        "for",
        "detail",
        "details",
    }
)


def _first_identifier(
    text: str, patterns: tuple[re.Pattern[str], ...], prefix: str
) -> str | None:
    """Return the first plausible identifier across *patterns*, in order."""

    for pattern in patterns:
        for match in pattern.finditer(text or ""):
            raw = match.group(1).strip().lower()
            if raw in _NON_IDENTIFIERS:
                continue
            return f"{prefix}-{raw}"
    return None


def extract_job_id(text: str) -> str | None:
    """Extract a job identifier from free-form customer text."""

    return _first_identifier(text, (_JOB_PREFIXED_RE, _JOB_SPACED_RE), "job")


def extract_invoice_id(text: str) -> str | None:
    """Extract an invoice identifier from free-form customer text."""

    return _first_identifier(
        text, (_INVOICE_PREFIXED_RE, _INVOICE_SPACED_RE), "invoice"
    )


class TriageLLM(Protocol):
    """LLM surface required by triage (mockable in tests)."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def requires_human_escalation(text: str, intent: TicketIntent) -> str | None:
    """Return a human-escalation reason, or ``None`` when none applies."""

    lowered = (text or "").lower()
    if intent is TicketIntent.HUMAN_ESCALATION:
        return "Customer explicitly requested a human agent."
    if any(keyword in lowered for keyword in _DISPUTE_KEYWORDS):
        return "Financial or billing dispute requires human review."
    if any(keyword in lowered for keyword in _SAFETY_KEYWORDS):
        return "Potential safety emergency requires human review."
    return None


class TriageAgent:
    """Classify a customer message and prepare the turn for a specialist."""

    name = TRIAGE

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        llm: TriageLLM | None = None,
        use_llm: bool = True,
        config_service: AgentConfigService | None = None,
    ) -> None:
        self._tools = tools
        self._llm = llm
        self._use_llm = use_llm and llm is not None
        self._config_service = config_service
        self.agent_type = AgentType.TRIAGE

    # ── Public entry point ────────────────────────────────────────────────

    def run(self, state: MultiAgentState, ctx: AgentContext) -> dict[str, Any]:
        """Produce the routing decision and ticket state for this turn."""

        message = state.get("user_message", "")
        decision = self._decide(message, state)
        human_reason = requires_human_escalation(message, decision.intent) or (
            decision.reasoning if decision.requires_human else None
        )

        if human_reason:
            decision = decision.model_copy(
                update={
                    "destination": AgentDestination.HUMAN,
                    "requires_human": True,
                }
            )

        destination = decision.destination
        updates: dict[str, Any] = {
            "intent": decision.intent.value,
            "category": decision.category.value,
            "priority": decision.priority,
            "destination": destination.value,
            "routing_reasoning": decision.reasoning,
            "requires_human": decision.requires_human,
            "human_reason": human_reason,
            "job_id": extract_job_id(message) or state.get("job_id"),
            "invoice_id": extract_invoice_id(message) or state.get("invoice_id"),
        }
        updates.update(self._sync_ticket(state, ctx, decision, message))
        return updates

    # ── Decision ──────────────────────────────────────────────────────────

    def _decide(self, message: str, state: MultiAgentState) -> RoutingDecision:
        deterministic = self._deterministic_decision(message, state)
        if not self._use_llm or self._llm is None:
            return deterministic
        # A forced human escalation is never overridden by the model.
        if deterministic.destination is AgentDestination.HUMAN:
            return deterministic
        refined = self._llm_decision(message, deterministic)
        return refined or deterministic

    def _deterministic_decision(
        self, message: str, state: MultiAgentState
    ) -> RoutingDecision:
        intent = classify_intent(message)
        # A conversation already routed to the job agent stays there when the
        # customer continues talking about that job.
        if (
            intent is TicketIntent.GENERAL_INQUIRY
            and state.get("job_id")
            and state.get("destination") == AgentDestination.JOB.value
        ):
            intent = TicketIntent.MODIFY_JOB

        destination = _INTENT_DESTINATIONS[intent]
        category = _INTENT_CATEGORIES[intent]
        human_reason = requires_human_escalation(message, intent)
        if human_reason:
            destination = AgentDestination.HUMAN

        return RoutingDecision(
            intent=intent,
            destination=destination,
            category=category,
            priority="medium",
            requires_human=destination is AgentDestination.HUMAN,
            reasoning=human_reason or f"Classified as {intent.value}.",
        )

    def _llm_decision(
        self, message: str, fallback: RoutingDecision
    ) -> RoutingDecision | None:
        assert self._llm is not None  # guarded by caller
        try:
            payload = self._llm.generate_json(
                f"{TRIAGE_INSTRUCTIONS}\n\n{ROUTING_SCHEMA_HINT}",
                message,
            )
        except Exception:  # noqa: BLE001 - model failure must not break triage
            return None
        decision = parse_routing_decision(payload)
        if decision is None:
            return None
        # Safety rules are not negotiable: never downgrade a deterministic
        # dispute/safety escalation into an automated destination.
        if fallback.destination is AgentDestination.HUMAN:
            return fallback
        return decision

    # ── Ticket lifecycle ──────────────────────────────────────────────────

    def _sync_ticket(
        self,
        state: MultiAgentState,
        ctx: AgentContext,
        decision: RoutingDecision,
        message: str,
    ) -> dict[str, Any]:
        """Reuse the active ticket when the issue is the same, else create one."""

        existing_id = state.get("ticket_id")
        existing = self._tools.execute(
            "find_active_ticket", ctx=ctx, calling_agent=self.name
        )
        active = existing.get("ticket") if existing.get("ok") else None
        if active is None and not existing_id:
            active = None

        if active:
            same_issue = self._is_same_issue(
                active.get("category"), decision.category.value
            )
            if same_issue or existing_id == active.get("id"):
                result = self._tools.execute(
                    "update_ticket",
                    ctx=ctx,
                    calling_agent=self.name,
                    arguments={
                        "ticket_id": active["id"],
                        "note": f"[{decision.intent.value}] {message}",
                    },
                )
                if result.get("ok"):
                    return {
                        "ticket_id": active["id"],
                        "ticket_action": TicketAction.UPDATE.value,
                    }
            # Different issue: fall through and open a new ticket.
        elif existing_id:
            return {"ticket_id": existing_id, "ticket_action": TicketAction.REUSE.value}

        return self._create_ticket(ctx, decision, message)

    @staticmethod
    def _is_same_issue(stored_category: Any, incoming_category: str) -> bool:
        if not stored_category:
            return False
        try:
            return normalize_ticket_category(str(stored_category)) == incoming_category
        except (TypeError, ValueError):
            return False

    def _create_ticket(
        self,
        ctx: AgentContext,
        decision: RoutingDecision,
        message: str,
    ) -> dict[str, Any]:
        title = message.strip().splitlines()[0][:120] or "Customer request"
        result = self._tools.execute(
            "create_ticket",
            ctx=ctx,
            calling_agent=self.name,
            arguments={
                "title": title,
                "description": message,
                "category": decision.category.value,
                "priority": decision.priority,
                "intent": decision.intent.value,
            },
        )
        if not result.get("ok"):
            # A ticket failure must not block the customer from getting help.
            return {"ticket_id": None, "ticket_action": TicketAction.NONE.value}
        ticket = result.get("ticket") or {}
        return {
            "ticket_id": ticket.get("id"),
            "ticket_action": TicketAction.CREATE.value,
        }
