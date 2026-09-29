"""Authorization-aware business operations for helpdesk workflows."""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from models import (
    HandledBy,
    TicketIntent,
    TicketStatus,
    normalize_ticket_category,
)
from utils.date_parser import parse_natural_datetime

_ALLOWED_JOB_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"cancelled", "scheduled", "locked"},
    "scheduled": {"cancelled", "in_progress", "locked"},
    "in_progress": {"completed", "cancelled"},
}


class AuthorizationError(PermissionError):
    """Raised when an actor attempts to access another customer's resource."""


class BusinessRuleError(ValueError):
    """Raised when a requested operation violates helpdesk business rules."""


@dataclass(frozen=True, slots=True)
class CustomerIdentity:
    """Authenticated customer context used for ownership checks."""

    customer_id: str
    email: str | None = None


def infer_required_skill(message: str) -> str | None:
    """Infer the required engineer skill from a customer's message text."""
    lowered = message.lower()
    dispute_keywords = (
        "refund",
        "chargeback",
        "legal",
        "overcharge",
        "double charge",
        "charged twice",
        "double charged",
        "billing issue",
        "billing dispute",
        "wrong charge",
        "incorrect charge",
        "unauthorized charge",
        "duplicate charge",
        "overcharged",
        "billing",
        "charged",
        "billing error",
    )
    if any(k in lowered for k in dispute_keywords):
        return None

    if any(
        k in lowered
        for k in (
            "ac",
            "air condition",
            "heating",
            "hvac",
            "cooling",
            "ventilation",
            "boiler",
        )
    ):
        return "HVAC"
    if any(
        k in lowered
        for k in ("toilet", "pipe", "leak", "plumb", "sink", "drain", "faucet")
    ):
        return "plumber"
    if any(
        k in lowered
        for k in ("electric", "wiring", "power", "breaker", "outlet", "light")
    ):
        return "electrical"
    if any(k in lowered for k in ("sanitary", "hygiene", "bathroom fixture")):
        return "sanitary"

    physical_markers = (
        "engineer",
        "technician",
        "plumber",
        "electrician",
        "hvac",
        "boiler",
        "heater",
        "appliance",
        "unit",
        "machine",
        "pipe",
        "toilet",
        "sink",
        "ac",
        "air condition",
    )
    if any(k in lowered for k in ("broken", "install", "installation")) and any(
        p in lowered for p in physical_markers
    ):
        return "technician"
    if any(k in lowered for k in ("repair", "fix", "maintenance", "job lock")):
        return "technician"
    return None


def _is_agent_only_intent(text: str) -> bool:
    """Return True when the message should not create a new Job."""
    from tools.classify_intent import classify_intent

    return classify_intent(text).is_agent_only


class HelpdeskOperationsService:
    """Perform customer-owned operations behind explicit authorization checks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def identify_customer_from_email(self, email: str) -> dict[str, Any] | None:
        """Return a verified customer by email, never auto-trusting unknown senders."""
        row = self._one(
            """SELECT * FROM customers
            WHERE lower(email) = lower(?) AND verification_status = 'verified'""",
            (email,),
        )
        return dict(row) if row else None

    def register_unverified_customer(
        self, *, name: str, email: str, phone: str, company: str
    ) -> dict[str, Any]:
        """Create a pending customer record unless the email already exists."""
        existing = self._one(
            "SELECT * FROM customers WHERE lower(email) = lower(?)", (email,)
        )
        if existing is not None:
            raise BusinessRuleError("customer email already exists")
        customer_id = f"customer-{uuid4().hex}"
        self.connection.execute(
            """INSERT INTO customers
            (id, name, email, phone, company, verification_status)
            VALUES (?, ?, ?, ?, ?, 'pending')""",
            (customer_id, name, email, phone, company),
        )
        self._audit(
            "system",
            None,
            "customer_registration_pending",
            "customer",
            customer_id,
            customer_id,
            {"email": email},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM customers WHERE id = ?", (customer_id,)))

    def create_ticket(
        self,
        identity: CustomerIdentity,
        *,
        title: str,
        description: str,
        category: str | None = None,
        priority: str | None = None,
        intent: str | None = None,
        handled_by: str = HandledBy.PENDING.value,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        """Create a ticket using the canonical ML category contract."""
        self._require_verified_customer(identity.customer_id)
        ticket_id = f"ticket-{uuid4().hex}"

        text = f"{title}. {description}"
        if intent:
            persisted_intent = TicketIntent(intent).value
        else:
            from tools.classify_intent import classify_intent

            persisted_intent = classify_intent(text).value
        persisted_handled_by = HandledBy(handled_by).value
        requested_category = (
            normalize_ticket_category(category) if category is not None else None
        )
        confidence = 1.0
        final_category = requested_category or "general"
        final_priority = priority or "medium"
        needs_escalation = 0
        escalation_reason = None

        try:
            from ml.classifier import TicketClassifier

            prediction = TicketClassifier().predict(text)
            if requested_category is None:
                final_category = normalize_ticket_category(prediction.category)
            if priority is None:
                final_priority = prediction.priority
            confidence = prediction.confidence_score
        except Exception:
            # Keep a valid canonical category when the optional ML model is
            # unavailable.  An explicitly supplied category is never replaced.
            if requested_category is None:
                final_category = "general"

        dispute_keywords = (
            "refund",
            "chargeback",
            "legal",
            "overcharge",
            "double charge",
            "charged twice",
            "double charged",
            "billing issue",
            "billing dispute",
            "wrong charge",
            "incorrect charge",
            "unauthorized charge",
            "duplicate charge",
            "overcharged",
            "billing error",
        )
        if any(keyword in text.lower() for keyword in dispute_keywords):
            needs_escalation = 1
            escalation_reason = (
                "Financial / billing dispute requires billing specialist review"
            )

        status = "escalated" if needs_escalation else "open"

        self.connection.execute(
            """INSERT INTO tickets
            (id, customer_id, title, description, category, priority, confidence,
             needs_escalation, escalation_reason, status, intent, handled_by,
             resolution)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticket_id,
                identity.customer_id,
                title,
                description,
                final_category,
                final_priority,
                confidence,
                needs_escalation,
                escalation_reason,
                status,
                persisted_intent,
                persisted_handled_by,
                resolution,
            ),
        )

        if needs_escalation:
            escalation_id = f"esc-{uuid4().hex}"
            self.connection.execute(
                """INSERT INTO escalations
                (id, ticket_id, customer_id, reason, context, status)
                VALUES (?, ?, ?, ?, ?, 'open')""",
                (
                    escalation_id,
                    ticket_id,
                    identity.customer_id,
                    escalation_reason or "Escalated during classification",
                    json.dumps(
                        {"title": title, "category": final_category}, sort_keys=True
                    ),
                ),
            )

        self._audit(
            "customer",
            identity.customer_id,
            "ticket_created",
            "ticket",
            ticket_id,
            identity.customer_id,
            {
                "title": title,
                "category": final_category,
                "confidence": confidence,
                "intent": persisted_intent,
            },
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))

    def get_customer_job(
        self, identity: CustomerIdentity, job_id: str
    ) -> dict[str, Any]:
        """Return a job only when it belongs to the authenticated customer."""
        job = self._owned_row("jobs", job_id, identity.customer_id)
        return dict(job)

    def create_job(
        self,
        identity: CustomerIdentity,
        *,
        title: str,
        description: str,
        required_skill: str,
        service_area: str,
        priority: str = "medium",
        scheduled_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a customer job after validating the customer and skill."""
        self._require_verified_customer(identity.customer_id)
        self._require_skill(required_skill)

        if scheduled_at is not None:
            self._validate_scheduled_at(scheduled_at)

        job_id = f"job-{uuid4().hex}"
        self.connection.execute(
            """INSERT INTO jobs
            (id, customer_id, title, description, status, priority,
             service_area, required_skill, scheduled_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
            (
                job_id,
                identity.customer_id,
                title,
                description,
                priority,
                service_area,
                required_skill,
                scheduled_at,
            ),
        )
        self._audit(
            "customer",
            identity.customer_id,
            "job_created",
            "job",
            job_id,
            identity.customer_id,
            {
                "required_skill": required_skill,
                "service_area": service_area,
                "scheduled_at": scheduled_at,
            },
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM jobs WHERE id = ?", (job_id,)))

    def cancel_customer_scheduled_jobs(
        self, customer_id: str, job_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Cancel active scheduled or pending jobs for a customer,
        optionally targeting a specific job_id."""
        if job_id:
            if job_id.isdigit():
                job_id = f"job-{job_id}"
            existing = self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))
            if existing is not None and existing["customer_id"] != customer_id:
                raise AuthorizationError(
                    f"job {job_id} does not belong to customer {customer_id}"
                )
            jobs = self.connection.execute(
                """SELECT * FROM jobs
                WHERE id = ? AND customer_id = ?
                AND status IN ('scheduled', 'pending', 'in_progress')""",
                (job_id, customer_id),
            ).fetchall()
            if jobs:
                self.connection.execute(
                    """UPDATE jobs SET status = 'cancelled'
                    WHERE id = ? AND customer_id = ?
                    AND status IN ('scheduled', 'pending', 'in_progress')""",
                    (job_id, customer_id),
                )
        else:
            jobs = self.connection.execute(
                """SELECT * FROM jobs
                WHERE customer_id = ?
                AND status IN ('scheduled', 'pending', 'in_progress')""",
                (customer_id,),
            ).fetchall()
            if jobs:
                self.connection.execute(
                    """UPDATE jobs SET status = 'cancelled'
                    WHERE customer_id = ?
                    AND status IN ('scheduled', 'pending', 'in_progress')""",
                    (customer_id,),
                )

        if jobs:
            for j in jobs:
                self._audit(
                    "customer",
                    customer_id,
                    "job_cancelled",
                    "job",
                    j["id"],
                    customer_id,
                    {"previous_status": j["status"]},
                )
            self.connection.commit()
        return [dict(j) for j in jobs]

    def find_best_engineer(
        self, *, required_skill: str, service_area: str
    ) -> sqlite3.Row | None:
        """Find the best eligible active engineer with matching skill and lowest
        workload."""
        row = self._one(
            """SELECT engineers.*
            FROM engineers
            JOIN engineer_skills ON engineer_skills.engineer_id = engineers.id
            WHERE engineers.active = 1
              AND engineers.service_area = ?
              AND engineers.current_workload < 5
              AND engineer_skills.skill = ?
            ORDER BY engineers.current_workload ASC, engineers.id ASC
            LIMIT 1""",
            (service_area, required_skill),
        )
        if row is None:
            row = self._one(
                """SELECT engineers.*
                FROM engineers
                JOIN engineer_skills ON engineer_skills.engineer_id = engineers.id
                WHERE engineers.active = 1
                  AND engineers.current_workload < 5
                  AND engineer_skills.skill = ?
                ORDER BY engineers.current_workload ASC, engineers.id ASC
                LIMIT 1""",
                (required_skill,),
            )
        return row

    def create_job_for_ticket(
        self,
        identity: CustomerIdentity,
        *,
        ticket_id: str,
        title: str,
        description: str,
        required_skill: str,
        service_area: str,
        priority: str = "medium",
        scheduled_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a job for a customer ticket, auto-assign an engineer, or record
        an escalation."""
        self._owned_row("tickets", ticket_id, identity.customer_id)
        self._require_verified_customer(identity.customer_id)
        self._require_skill(required_skill)

        if scheduled_at is not None:
            self._validate_scheduled_at(scheduled_at)

        job_id = f"job-{uuid4().hex}"
        self.connection.execute(
            """INSERT INTO jobs
            (id, customer_id, title, description, status, priority,
             service_area, required_skill, scheduled_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
            (
                job_id,
                identity.customer_id,
                title,
                description,
                priority,
                service_area,
                required_skill,
                scheduled_at,
            ),
        )

        self.connection.execute(
            "UPDATE tickets SET job_id = ?, related_job_id = ? WHERE id = ?",
            (job_id, job_id, ticket_id),
        )

        engineer = self.find_best_engineer(
            required_skill=required_skill, service_area=service_area
        )

        if engineer is not None:
            engineer_id = str(engineer["id"])
            self.connection.execute(
                """UPDATE jobs
                SET assigned_engineer_id = ?, status = 'scheduled'
                WHERE id = ?""",
                (engineer_id, job_id),
            )
            self.connection.execute(
                """UPDATE tickets
                SET assigned_engineer_id = ?, status = 'in_progress'
                WHERE id = ?""",
                (engineer_id, ticket_id),
            )
            self.connection.execute(
                "UPDATE engineers SET current_workload = current_workload + 1 "
                "WHERE id = ?",
                (engineer_id,),
            )
            self._audit(
                "system",
                None,
                "job_auto_assigned_engineer",
                "job",
                job_id,
                identity.customer_id,
                {"engineer_id": engineer_id, "ticket_id": ticket_id},
            )
        else:
            escalation_reason = (
                f"No eligible engineer available for skill '{required_skill}' "
                f"in area '{service_area}'"
            )
            self.connection.execute(
                """UPDATE tickets
                SET needs_escalation = 1, status = 'escalated', escalation_reason = ?
                WHERE id = ?""",
                (escalation_reason, ticket_id),
            )
            escalation_id = f"esc-{uuid4().hex}"
            self.connection.execute(
                """INSERT INTO escalations
                (id, ticket_id, customer_id, reason, context, status)
                VALUES (?, ?, ?, ?, ?, 'open')""",
                (
                    escalation_id,
                    ticket_id,
                    identity.customer_id,
                    escalation_reason,
                    json.dumps(
                        {
                            "job_id": job_id,
                            "required_skill": required_skill,
                            "service_area": service_area,
                        },
                        sort_keys=True,
                    ),
                ),
            )
            self._audit(
                "system",
                None,
                "ticket_escalated",
                "ticket",
                ticket_id,
                identity.customer_id,
                {"reason": escalation_reason, "escalation_id": escalation_id},
            )

        self.connection.commit()
        updated_ticket = dict(
            self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        )
        updated_job = dict(self._one("SELECT * FROM jobs WHERE id = ?", (job_id,)))
        return {"ticket": updated_ticket, "job": updated_job}

    def lock_job(self, identity: CustomerIdentity, job_id: str) -> dict[str, Any]:
        """Reserve a customer-owned job when it is in a lockable state."""
        job = dict(self._owned_row("jobs", job_id, identity.customer_id))
        if job["status"] not in {"pending", "scheduled"}:
            raise BusinessRuleError(f"job cannot be locked from status {job['status']}")
        self.connection.execute(
            "UPDATE jobs SET status = 'locked' WHERE id = ?", (job_id,)
        )
        self._audit(
            "customer",
            identity.customer_id,
            "job_locked",
            "job",
            job_id,
            identity.customer_id,
            {"previous_status": job["status"]},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM jobs WHERE id = ?", (job_id,)))

    def assign_engineer(
        self, *, job_id: str, engineer_id: str, reviewer: str
    ) -> dict[str, Any]:
        """Assign an eligible engineer using structured skill/area/workload rules."""
        job = self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job is None:
            raise LookupError(f"job does not exist: {job_id}")
        engineer = self._eligible_engineer(
            engineer_id=engineer_id,
            required_skill=job["required_skill"],
            service_area=job["service_area"],
        )
        if engineer is None:
            raise BusinessRuleError("engineer is not eligible for this job")
        self.connection.execute(
            """UPDATE jobs
            SET assigned_engineer_id = ?, status = 'scheduled'
            WHERE id = ?""",
            (engineer_id, job_id),
        )
        self.connection.execute(
            "UPDATE engineers SET current_workload = current_workload + 1 WHERE id = ?",
            (engineer_id,),
        )
        self._audit(
            "human",
            reviewer,
            "engineer_assigned",
            "job",
            job_id,
            job["customer_id"],
            {"engineer_id": engineer_id},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM jobs WHERE id = ?", (job_id,)))

    def create_email_draft(
        self, *, ticket_id: str, customer_id: str, ai_draft: str
    ) -> dict[str, Any]:
        """Store an AI email draft in human review; this method never sends email."""
        ticket = self._owned_row("tickets", ticket_id, customer_id)
        # A ticket with an outstanding draft is still being worked.  In
        # particular, do not leave it resolved while a human response is
        # awaiting approval.
        self.connection.execute(
            "UPDATE tickets SET status = 'in_progress' WHERE id = ?",
            (ticket["id"],),
        )
        draft_id = f"draft-{uuid4().hex}"
        self.connection.execute(
            """INSERT INTO email_drafts
            (id, ticket_id, customer_id, original_ai_draft, status)
            VALUES (?, ?, ?, ?, 'human_review')""",
            (draft_id, ticket["id"], customer_id, ai_draft),
        )
        self._audit(
            "agent",
            None,
            "email_draft_created",
            "email_draft",
            draft_id,
            customer_id,
            {"ticket_id": ticket_id},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM email_drafts WHERE id = ?", (draft_id,)))

    def approve_email_draft(
        self, *, draft_id: str, reviewer: str, edited_body: str | None = None
    ) -> dict[str, Any]:
        """Approve a draft after optional human edits."""
        draft = self._draft_for_review(draft_id)
        final_body = (
            edited_body if edited_body is not None else draft["original_ai_draft"]
        )
        self.connection.execute(
            """UPDATE email_drafts
            SET human_edited_version = ?, reviewer = ?, status = 'approved',
                reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?""",
            (edited_body, reviewer, draft_id),
        )
        # Approval is the point at which the pending response has cleared
        # human review.  Resolve the associated ticket only now.
        self.connection.execute(
            "UPDATE tickets SET status = 'resolved' WHERE id = ?",
            (draft["ticket_id"],),
        )
        self._audit(
            "human",
            reviewer,
            "email_draft_approved",
            "email_draft",
            draft_id,
            draft["customer_id"],
            {"edited": edited_body is not None, "final_length": len(final_body)},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM email_drafts WHERE id = ?", (draft_id,)))

    def reject_email_draft(
        self, *, draft_id: str, reviewer: str, reason: str
    ) -> dict[str, Any]:
        """Reject an AI draft so the agent or a human can regenerate/respond."""
        draft = self._draft_for_review(draft_id)
        self.connection.execute(
            """UPDATE email_drafts
            SET reviewer = ?, status = 'rejected', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?""",
            (reviewer, draft_id),
        )
        self._audit(
            "human",
            reviewer,
            "email_draft_rejected",
            "email_draft",
            draft_id,
            draft["customer_id"],
            {"reason": reason},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM email_drafts WHERE id = ?", (draft_id,)))

    def send_approved_email(self, *, draft_id: str, sender: str) -> dict[str, Any]:
        """Send an approved email draft, executing deferred job creation,
        creating a sent_emails record, and removing the draft."""
        draft = self._one("SELECT * FROM email_drafts WHERE id = ?", (draft_id,))
        if draft is None:
            raise LookupError(f"email draft does not exist: {draft_id}")
        if draft["status"] != "approved":
            raise BusinessRuleError("email draft must be approved before sending")

        ticket = self._one("SELECT * FROM tickets WHERE id = ?", (draft["ticket_id"],))
        created_job_id: str | None = None
        if self._should_create_job_for_ticket(ticket):
            inferred_skill = infer_required_skill(ticket["description"])
            if inferred_skill is not None:
                parsed_dt = parse_natural_datetime(ticket["description"])
                # If the customer did not request a specific time, reserve a
                # near-term appointment when the approved email is sent.
                # Keep this here (rather than at draft creation) so approval
                # remains the point at which the job is actually created.
                if parsed_dt is None:
                    scheduled_dt = datetime.now() + timedelta(
                        minutes=random.randint(120, 180)
                    )
                    scheduled_at_iso = scheduled_dt.isoformat()
                else:
                    scheduled_at_iso = parsed_dt.isoformat()
                try:
                    created_job = self.create_job_for_ticket(
                        CustomerIdentity(customer_id=draft["customer_id"]),
                        ticket_id=draft["ticket_id"],
                        title=f"{inferred_skill} Service Visit",
                        description=ticket["description"],
                        required_skill=inferred_skill,
                        service_area="London",
                        scheduled_at=scheduled_at_iso,
                    )
                    # create_job_for_ticket returns the job nested under
                    # ``job``; reading the top-level ID silently left the
                    # successful scheduling response without a job ID.
                    created_job_id = (created_job.get("job") or {}).get("id")
                except Exception:
                    pass

        final_message = draft["human_edited_version"] or draft["original_ai_draft"]
        if created_job_id and created_job_id not in final_message:
            final_message = (
                f"{final_message}\n\nYour job ID is {created_job_id}. "
                "Please keep this ID for future reference."
            )
        sent_id = f"sent-{uuid4().hex}"

        self.connection.execute(
            """INSERT INTO sent_emails
            (id, draft_id, ticket_id, customer_id, sender, body)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                sent_id,
                draft_id,
                draft["ticket_id"],
                draft["customer_id"],
                sender,
                final_message,
            ),
        )

        self.connection.execute("DELETE FROM email_drafts WHERE id = ?", (draft_id,))

        self._audit(
            "human",
            sender,
            "email_sent",
            "sent_email",
            sent_id,
            draft["customer_id"],
            {"ticket_id": draft["ticket_id"], "draft_id": draft_id},
        )

        self.connection.commit()
        sent_row = dict(self._one("SELECT * FROM sent_emails WHERE id = ?", (sent_id,)))
        sent_row["status"] = "sent"
        sent_row["final_sent_message"] = final_message
        return sent_row

    def resolve_ticket_as_agent(
        self, ticket_id: str, resolution: str
    ) -> dict[str, Any]:
        """Mark a ticket as resolved by the AI agent with no new Job."""
        ticket = self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if ticket is None:
            raise LookupError(f"ticket does not exist: {ticket_id}")
        self.connection.execute(
            """UPDATE tickets
            SET status = ?, handled_by = ?, resolution = ?, related_job_id = NULL
            WHERE id = ?""",
            (
                TicketStatus.RESOLVED.value,
                HandledBy.AI_AGENT.value,
                resolution,
                ticket_id,
            ),
        )
        self._audit(
            "agent",
            None,
            "ticket_resolved_by_agent",
            "ticket",
            ticket_id,
            ticket["customer_id"],
            {"resolution": resolution},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))

    def link_ticket_to_job(self, ticket_id: str, job_id: str) -> dict[str, Any]:
        """Associate an existing ticket with an existing job."""
        ticket = self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if ticket is None:
            raise LookupError(f"ticket does not exist: {ticket_id}")
        job = self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job is None:
            raise LookupError(f"job does not exist: {job_id}")
        if job["customer_id"] != ticket["customer_id"]:
            raise AuthorizationError(
                "job does not belong to the same customer as the ticket"
            )
        self.connection.execute(
            "UPDATE tickets SET related_job_id = ? WHERE id = ?",
            (job_id, ticket_id),
        )
        self._audit(
            "system",
            None,
            "ticket_linked_to_job",
            "ticket",
            ticket_id,
            ticket["customer_id"],
            {"job_id": job_id},
        )
        self.connection.commit()
        return dict(self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))

    def cancel_job_for_ticket(
        self,
        customer_id: str,
        ticket_id: str,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Cancel owned jobs for a ticket and resolve the ticket as the agent."""
        self._owned_row("tickets", ticket_id, customer_id)
        cancelled = self.cancel_customer_scheduled_jobs(customer_id, job_id=job_id)
        if cancelled:
            cancelled_ids = ", ".join(job["id"] for job in cancelled)
            resolution = f"Cancelled job(s): {cancelled_ids}"
        else:
            resolution = "No active scheduled or pending jobs to cancel"
        ticket = self.resolve_ticket_as_agent(ticket_id, resolution)
        if cancelled:
            ticket = self.link_ticket_to_job(ticket_id, cancelled[0]["id"])
        return {"ticket": ticket, "cancelled_jobs": cancelled}

    def update_customer_job_status(
        self,
        identity: CustomerIdentity,
        job_id: str,
        new_status: str,
    ) -> dict[str, Any]:
        """Update a customer-owned job after validating the status transition."""
        if job_id.isdigit():
            job_id = f"job-{job_id}"
        job = dict(self._owned_row("jobs", job_id, identity.customer_id))
        current_status = job["status"]
        allowed = _ALLOWED_JOB_STATUS_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise BusinessRuleError(
                f"Cannot transition job '{job_id}' from status '{current_status}' "
                f"to '{new_status}'. Allowed transitions: {sorted(allowed)}"
            )
        self.connection.execute(
            "UPDATE jobs SET status = ? WHERE id = ? AND customer_id = ?",
            (new_status, job_id, identity.customer_id),
        )
        self._audit(
            "customer",
            identity.customer_id,
            "job_status_updated",
            "job",
            job_id,
            identity.customer_id,
            {"previous_status": current_status, "new_status": new_status},
        )
        self.connection.commit()
        updated = dict(self._one("SELECT * FROM jobs WHERE id = ?", (job_id,)))
        return {"found": True, "job": updated, "previous_status": current_status}

    def reschedule_customer_job(
        self, identity: CustomerIdentity, job_id: str, scheduled_at: str
    ) -> dict[str, Any]:
        """Change an owned job's appointment time and keep it scheduled."""
        job = self._owned_row("jobs", job_id, identity.customer_id)
        self._validate_scheduled_at(scheduled_at)
        self.connection.execute(
            "UPDATE jobs SET scheduled_at = ?, status = 'scheduled' WHERE id = ?",
            (scheduled_at, job_id),
        )
        self._audit(
            "customer",
            identity.customer_id,
            "job_rescheduled",
            "job",
            job_id,
            identity.customer_id,
            {"scheduled_at": scheduled_at},
        )
        self.connection.commit()
        updated = dict(self._one("SELECT * FROM jobs WHERE id = ?", (job_id,)))
        return {"found": True, "job": updated, "previous_status": job["status"]}

    def _should_create_job_for_ticket(self, ticket: sqlite3.Row | None) -> bool:
        if ticket is None:
            return False
        if ticket["job_id"]:
            return False
        intent_value = ticket["intent"] if "intent" in ticket.keys() else None
        if intent_value:
            try:
                intent = TicketIntent(intent_value)
                if intent.is_agent_only:
                    return False
                if intent is TicketIntent.NEW_SERVICE_REQUEST:
                    return True
            except ValueError:
                pass
        if ticket["needs_escalation"] or ticket["category"] == "billing":
            return False
        if _is_agent_only_intent(ticket["description"]):
            return False
        # A concrete service request must still create its job even when the
        # classifier marked the ticket for review due to low confidence.
        if infer_required_skill(ticket["description"]) is not None:
            return True
        return True

    def _require_verified_customer(self, customer_id: str) -> None:
        customer = self._one(
            "SELECT * FROM customers WHERE id = ? AND verification_status = 'verified'",
            (customer_id,),
        )
        if customer is None:
            raise AuthorizationError("customer is not verified or does not exist")

    def _owned_row(self, table: str, resource_id: str, customer_id: str) -> sqlite3.Row:
        row = self._one(f"SELECT * FROM {table} WHERE id = ?", (resource_id,))
        if row is None:
            raise LookupError(f"{table} resource does not exist: {resource_id}")
        if row["customer_id"] != customer_id:
            raise AuthorizationError(
                "resource does not belong to authenticated customer"
            )
        return row

    def _draft_for_review(self, draft_id: str) -> sqlite3.Row:
        draft = self._one("SELECT * FROM email_drafts WHERE id = ?", (draft_id,))
        if draft is None:
            raise LookupError(f"email draft does not exist: {draft_id}")
        if draft["status"] != "human_review":
            raise BusinessRuleError("email draft is not awaiting human review")
        return draft

    def _eligible_engineer(
        self, *, engineer_id: str, required_skill: str | None, service_area: str | None
    ) -> sqlite3.Row | None:
        if not required_skill or not service_area:
            return None
        return self._one(
            """SELECT engineers.*
            FROM engineers
            JOIN engineer_skills ON engineer_skills.engineer_id = engineers.id
            WHERE engineers.id = ?
              AND engineers.active = 1
              AND engineers.service_area = ?
              AND engineers.current_workload < 5
              AND engineer_skills.skill = ?""",
            (engineer_id, service_area, required_skill),
        )

    def _require_skill(self, skill: str) -> None:
        allowed = {"technician", "plumber", "HVAC", "electrical", "sanitary"}
        if skill not in allowed:
            raise BusinessRuleError(f"unsupported required skill: {skill}")

    def _validate_scheduled_at(self, scheduled_at: str) -> None:
        """Validate that scheduled_at is a valid ISO format datetime in the future."""
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_at)
        except (ValueError, TypeError) as e:
            raise BusinessRuleError(
                f"invalid datetime format: {scheduled_at}. "
                "Use ISO format (e.g., 2026-09-18T09:00:00)"
            ) from e

        if scheduled_dt <= datetime.now():
            raise BusinessRuleError("scheduled_at must be a future date and time")

    def _audit(
        self,
        actor_type: str,
        actor_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        customer_id: str | None,
        details: dict[str, Any],
    ) -> None:
        self.connection.execute(
            """INSERT INTO audit_log
            (id, actor_type, actor_id, action, resource_type, resource_id,
             customer_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"audit-{uuid4().hex}",
                actor_type,
                actor_id,
                action,
                resource_type,
                resource_id,
                customer_id,
                json.dumps(details, sort_keys=True),
            ),
        )

    def _one(self, query: str, parameters: tuple[Any, ...]) -> sqlite3.Row | None:
        return self.connection.execute(query, parameters).fetchone()
