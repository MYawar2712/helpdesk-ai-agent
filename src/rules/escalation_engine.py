"""Business rule engine for automated ticket routing and escalation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from models import EscalationResult


class EscalationEngine:
    """Apply deterministic business rules to a ticket and ML prediction."""

    CONFIDENCE_THRESHOLD = 0.60
    DISPUTE_KEYWORDS = ("refund", "chargeback", "legal", "overcharge")
    CATEGORY_QUEUES = {
        "billing": "billing_queue",
        "outage": "technical_outage_queue",
        "hardware": "hardware_support_queue",
        "general_inquiry": "general_support_queue",
    }

    def evaluate_ticket_rules(
        self, ticket_context: dict[str, Any], ml_prediction: dict[str, Any]
    ) -> EscalationResult:
        """Evaluate ML output and the ticket's customer context."""

        confidence = self._number(ml_prediction.get("confidence_score"), 0.0)
        category = self._text(ml_prediction.get("category"), "general_inquiry")
        priority = self._text(ml_prediction.get("priority"), "medium").lower()
        ticket = self._mapping(ticket_context.get("ticket"))
        text = " ".join(
            self._text(ticket.get(field), "") for field in ("title", "description")
        ).lower()
        category_text = category.lower()
        reasons: list[str] = []
        should_escalate = False
        requires_human_handoff = False
        priority_override: str | None = None

        if confidence < self.CONFIDENCE_THRESHOLD:
            requires_human_handoff = True
            should_escalate = True
            reasons.append("ML confidence is below the human-review threshold")

        overdue_total = self._overdue_total(ticket_context.get("open_invoices"))
        if overdue_total > 1000 or priority == "urgent":
            should_escalate = True
            priority_override = "urgent"
            reasons.append(
                "VIP escalation triggered by overdue balance or urgent priority"
            )

        if any(
            keyword in text or keyword in category_text
            for keyword in self.DISPUTE_KEYWORDS
        ):
            should_escalate = True
            requires_human_handoff = True
            priority_override = priority_override or "high"
            reasons.append("Financial dispute requires billing specialist review")
            queue = "billing_specialists"
        elif confidence < self.CONFIDENCE_THRESHOLD:
            queue = "tier_1_manual_review"
        elif overdue_total > 1000 or priority == "urgent":
            queue = "vip_priority_queue"
        else:
            queue = self.CATEGORY_QUEUES.get(category_text, "general_support_queue")

        return EscalationResult(
            should_escalate=should_escalate,
            target_queue=queue,
            priority_override=priority_override,
            requires_human_handoff=requires_human_handoff,
            reasons=reasons,
        )

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _text(value: object, default: str) -> str:
        return value if isinstance(value, str) else default

    @staticmethod
    def _number(value: object, default: float) -> float:
        return float(value) if isinstance(value, int | float) else default

    @classmethod
    def _overdue_total(cls, invoices: object) -> float:
        if not isinstance(invoices, list):
            return 0.0
        total = 0.0
        for invoice in invoices:
            row = cls._mapping(invoice)
            status = cls._text(row.get("status"), "").lower()
            if status in {"overdue", "unpaid"}:
                amount = row.get("amount", 0.0)
                if isinstance(amount, int | float):
                    total += float(amount)
                else:
                    try:
                        total += float(str(amount))
                    except ValueError:
                        continue
        return total
