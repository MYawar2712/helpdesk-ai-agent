"""Centralized approval policy for agent actions (Day 9).

One place decides whether an action needs human approval. Agents never embed
this logic, and it is never expressed in an LLM prompt.

Precedence is strict::

    Platform safety policy      (cannot be weakened)
        ↓
    Tenant approval policy      (can only add requirements)
        ↓
    Action decision

A tenant may *require* approval for more actions than the platform does, but can
never remove a platform-mandated requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.actions import ActionRisk, AgentAction

#: Platform defaults, deliberately conservative. The tuple is
#: ``(risk, requires_approval)``.
_PLATFORM_ACTIONS: dict[str, tuple[ActionRisk, bool]] = {
    # Reads and informational answers are always safe.
    "get_job": (ActionRisk.LOW, False),
    "get_customer_jobs": (ActionRisk.LOW, False),
    "get_customer_invoices": (ActionRisk.LOW, False),
    "get_invoice": (ActionRisk.LOW, False),
    "get_engineers": (ActionRisk.LOW, False),
    "get_support_information": (ActionRisk.LOW, False),
    "search_knowledge": (ActionRisk.LOW, False),
    "find_active_ticket": (ActionRisk.LOW, False),
    # Creation is a real side effect: approval required by default.
    "create_ticket": (ActionRisk.MEDIUM, True),
    "update_ticket": (ActionRisk.LOW, False),
    "create_job": (ActionRisk.MEDIUM, True),
    "update_job_status": (ActionRisk.HIGH, True),
    "reschedule_job": (ActionRisk.HIGH, True),
    "cancel_job": (ActionRisk.HIGH, True),
    "assign_engineer": (ActionRisk.MEDIUM, True),
    "create_invoice": (ActionRisk.CRITICAL, True),
    "update_invoice": (ActionRisk.CRITICAL, True),
    "send_email": (ActionRisk.CRITICAL, True),
    "issue_refund": (ActionRisk.CRITICAL, True),
}

#: Any action not listed above is treated as high risk and gated.
_UNKNOWN_ACTION = (ActionRisk.HIGH, True)


@dataclass(frozen=True, slots=True)
class ApprovalRequirement:
    """Outcome of evaluating an action against the policy."""

    requires_approval: bool
    risk_level: ActionRisk
    #: Why the decision was reached, for audit metadata.
    source: str
    action_type: str


@dataclass
class ApprovalPolicy:
    """Platform policy plus optional tenant additions."""

    #: Actions a tenant has opted into reviewing.
    tenant_required_actions: frozenset[str] = field(default_factory=frozenset)
    #: Actions a tenant asked to exempt. Exemptions are ignored for any action
    #: the platform already requires approval for.
    tenant_exempt_actions: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_tenant_config(cls, config: Any) -> ApprovalPolicy:
        """Build a policy from a Day 8 :class:`~agents.config.AgentConfig`.

        Tenant business rules are read from the ``business_rules`` list, using
        the keys ``require_human_approval_for`` and ``no_human_approval_for``.
        """

        required: set[str] = set()
        exempt: set[str] = set()
        for rule in getattr(config, "business_rules", None) or []:
            key, _, raw = str(rule).partition("=")
            key = key.strip().lower()
            values = frozenset(
                item.strip().lower() for item in raw.split(",") if item.strip()
            )
            if key == "require_human_approval_for":
                required |= values
            elif key == "no_human_approval_for":
                exempt |= values
        return cls(
            tenant_required_actions=frozenset(required),
            tenant_exempt_actions=frozenset(exempt),
        )


def evaluate(
    action: AgentAction, policy: ApprovalPolicy | None = None
) -> ApprovalRequirement:
    """Return whether *action* requires human approval.

    The tenant policy is applied on top of the platform policy and may only
    increase strictness.
    """

    policy = policy or ApprovalPolicy()
    platform_risk, platform_requires = _PLATFORM_ACTIONS.get(
        action.action_type, _UNKNOWN_ACTION
    )

    if action.action_type in policy.tenant_required_actions:
        return ApprovalRequirement(
            requires_approval=True,
            risk_level=platform_risk,
            source="tenant_policy",
            action_type=action.action_type,
        )

    if platform_requires:
        return ApprovalRequirement(
            requires_approval=True,
            risk_level=platform_risk,
            source="platform_policy",
            action_type=action.action_type,
        )

    # Platform allows it. A tenant exemption here is a no-op because the
    # platform already permitted the action.
    return ApprovalRequirement(
        requires_approval=False,
        risk_level=platform_risk,
        source="platform_policy",
        action_type=action.action_type,
    )


def risk_for(action_type: str) -> ActionRisk:
    """Return the platform risk level for an action type."""

    return _PLATFORM_ACTIONS.get(action_type, _UNKNOWN_ACTION)[0]
