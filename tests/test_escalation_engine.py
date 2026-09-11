from models import EscalationResult
from rules.escalation_engine import EscalationEngine


def context(**ticket: object) -> dict:
    return {"ticket": ticket, "open_invoices": []}


def prediction(**values: object) -> dict:
    return {
        "category": "general_inquiry",
        "priority": "low",
        "confidence_score": 0.95,
        **values,
    }


def test_low_confidence_requires_manual_handoff() -> None:
    result = EscalationEngine().evaluate_ticket_rules(
        context(title="Unclear issue"), prediction(confidence_score=0.42)
    )
    assert result == EscalationResult(
        should_escalate=True,
        target_queue="tier_1_manual_review",
        priority_override=None,
        requires_human_handoff=True,
        reasons=["ML confidence is below the human-review threshold"],
    )


def test_high_value_urgent_ticket_uses_vip_queue() -> None:
    result = EscalationEngine().evaluate_ticket_rules(
        context(
            title="Service issue", open_invoices=[{"status": "overdue", "amount": 1500}]
        ),
        prediction(category="outage", priority="urgent"),
    )
    assert result.target_queue == "vip_priority_queue"
    assert result.should_escalate is True
    assert result.priority_override == "urgent"


def test_financial_dispute_uses_billing_specialists() -> None:
    result = EscalationEngine().evaluate_ticket_rules(
        context(title="Unexpected overcharge on invoice"),
        prediction(category="billing"),
    )
    assert result.target_queue == "billing_specialists"
    assert result.requires_human_handoff is True
    assert result.should_escalate is True


def test_standard_ticket_uses_category_queue() -> None:
    result = EscalationEngine().evaluate_ticket_rules(
        context(title="Replace keyboard"),
        prediction(category="hardware", priority="low"),
    )
    assert result.target_queue == "hardware_support_queue"
    assert result.should_escalate is False
    assert result.requires_human_handoff is False
