"""Structured, validated decisions exchanged between Day 7 agents.

Routing never relies on free-form LLM text. Every hop is described by a
Pydantic model that is validated before it can influence control flow, and every
``destination`` is constrained to :class:`AgentDestination`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import TicketCategory, TicketIntent


class AgentDestination(StrEnum):
    """The specialized agent that should handle the current turn."""

    SUPPORT = "support"
    JOB = "job"
    INVOICE = "invoice"
    HUMAN = "human"


class TicketAction(StrEnum):
    """What triage decided to do with the helpdesk ticket for this turn."""

    CREATE = "create"
    UPDATE = "update"
    REUSE = "reuse"
    NONE = "none"


class AgentResult(BaseModel):
    """Structured result returned by a specialized agent.

    Agents pass this object between each other rather than free-form text, so
    the supervisor can decide programmatically what to do next.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    message: str
    agent: str
    action_taken: str | None = None
    requires_human: bool = False
    reason: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("agent result message must not be empty")
        return value.strip()


class RoutingDecision(BaseModel):
    """Validated triage decision that selects the next agent.

    ``intent`` and ``destination`` are constrained to the canonical domain
    enums, so a malformed or hallucinated value cannot steer the workflow.
    """

    model_config = ConfigDict(extra="forbid")

    intent: TicketIntent
    destination: AgentDestination
    category: TicketCategory
    priority: Literal["low", "medium", "high"]
    requires_human: bool = False
    reasoning: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("requires_human")
    @classmethod
    def _human_requires_destination(cls, value: bool, info: Any) -> bool:
        """A human request must actually route to the human agent."""

        destination = info.data.get("destination")
        if value and destination is not None and destination != AgentDestination.HUMAN:
            raise ValueError("requires_human=True requires destination='human'")
        return value


class TriageOutcome(BaseModel):
    """Triage's full output, including ticket lifecycle decisions."""

    model_config = ConfigDict(extra="forbid")

    decision: RoutingDecision
    ticket_action: TicketAction
    ticket_title: str | None = None
    job_id: str | None = None
    invoice_id: str | None = None


def parse_routing_decision(payload: dict[str, Any]) -> RoutingDecision | None:
    """Validate an LLM payload into a :class:`RoutingDecision`.

    Returns ``None`` when the payload is not valid, so the caller can fall back
    to the deterministic classifier instead of crashing the workflow.
    """

    try:
        return RoutingDecision.model_validate(payload)
    except Exception:  # noqa: BLE001 - invalid model output must not be fatal
        return None
