"""Structured agent action proposals and approval state (Day 9).

Agents never execute a high-risk operation directly. They emit a validated
:class:`AgentAction`, which the approval policy classifies and — when required —
pauses the graph for a human decision.

Free-form LLM text is never used as an approval payload: ``AgentAction`` is a
Pydantic model, so the stored request is machine-readable and replayable.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActionRisk(StrEnum):
    """Platform-assigned risk level for a proposed action."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalStatus(StrEnum):
    """Lifecycle of an approval request.

    ``EXECUTING`` and ``EXECUTED`` exist so an approved action can be claimed
    exactly once, which is what prevents duplicate execution.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


#: Statuses from which no further transition is allowed.
TERMINAL_STATUSES = frozenset(
    {
        ApprovalStatus.REJECTED.value,
        ApprovalStatus.EXPIRED.value,
        ApprovalStatus.CANCELLED.value,
        ApprovalStatus.EXECUTED.value,
        ApprovalStatus.FAILED.value,
    }
)


class EscalationKind(StrEnum):
    """Why a turn needs a human.

    Day 9 separates "waiting for an approval decision" from "needs human
    support intervention"; the two are handled by different mechanisms.
    """

    NONE = "NONE"
    APPROVAL = "APPROVAL"
    ESCALATED = "ESCALATED"


class AgentAction(BaseModel):
    """A validated, replayable description of an action an agent wants to take."""

    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1, max_length=100)
    resource_type: str = Field(min_length=1, max_length=100)
    resource_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("action_type", "resource_type", mode="before")
    @classmethod
    def _normalize(cls, value: str) -> str:
        # Normalising *before* the length constraints run means a whitespace-only
        # value is rejected instead of being stripped to an empty string.
        return value.strip().lower() if isinstance(value, str) else value

    def fingerprint(self) -> str:
        """Return a stable key for this action.

        Used to detect that a resumed turn is proposing the same action again,
        so a replayed graph node does not create duplicate approval requests.
        """

        return f"{self.action_type}:{self.resource_type}:{self.resource_id or ''}"


class ApprovalDecision(BaseModel):
    """The human decision returned to a paused graph on resume."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str
    decision: str = Field(description="approved, rejected, or expired")
    reviewer_id: str | None = None
    comment: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision.lower() == "approved"
