import sqlite3

import pytest

from db.seed import seed_database
from services.operations import (
    AuthorizationError,
    BusinessRuleError,
    CustomerIdentity,
    HelpdeskOperationsService,
)


def make_service() -> HelpdeskOperationsService:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    return HelpdeskOperationsService(connection)


def test_customer_cannot_read_another_customers_job() -> None:
    service = make_service()

    with pytest.raises(AuthorizationError):
        service.get_customer_job(CustomerIdentity("customer-2"), "job-1")


def test_customer_can_create_and_lock_own_job_with_audit() -> None:
    service = make_service()

    job = service.create_job(
        CustomerIdentity("customer-1"),
        title="AC is broken",
        description="Please send someone tomorrow.",
        required_skill="HVAC",
        service_area="London",
    )
    locked = service.lock_job(CustomerIdentity("customer-1"), job["id"])

    assert locked["status"] == "locked"
    audit_actions = [
        row[0]
        for row in service.connection.execute(
            "SELECT action FROM audit_log WHERE resource_id = ? ORDER BY created_at",
            (job["id"],),
        )
    ]
    assert audit_actions == ["job_created", "job_locked"]


def test_engineer_assignment_requires_skill_area_and_active_status() -> None:
    service = make_service()
    job = service.create_job(
        CustomerIdentity("customer-1"),
        title="AC is broken",
        description="Unit is blowing warm air.",
        required_skill="HVAC",
        service_area="London",
    )

    with pytest.raises(BusinessRuleError):
        service.assign_engineer(
            job_id=job["id"], engineer_id="engineer-2", reviewer="support-1"
        )

    assigned = service.assign_engineer(
        job_id=job["id"], engineer_id="engineer-1", reviewer="support-1"
    )
    assert assigned["assigned_engineer_id"] == "engineer-1"
    assert assigned["status"] == "scheduled"


def test_email_draft_requires_human_approval_before_send() -> None:
    service = make_service()
    draft = service.create_email_draft(
        ticket_id="ticket-1",
        customer_id="customer-1",
        ai_draft="We can send an HVAC technician tomorrow.",
    )

    with pytest.raises(BusinessRuleError):
        service.send_approved_email(draft_id=draft["id"], sender="support-1")

    approved = service.approve_email_draft(
        draft_id=draft["id"],
        reviewer="support-1",
        edited_body="We can send an HVAC technician tomorrow morning.",
    )
    sent = service.send_approved_email(draft_id=approved["id"], sender="support-1")

    assert sent["status"] == "sent"
    assert (
        sent["final_sent_message"] == "We can send an HVAC technician tomorrow morning."
    )


def test_rejected_email_cannot_be_sent() -> None:
    service = make_service()
    draft = service.create_email_draft(
        ticket_id="ticket-1",
        customer_id="customer-1",
        ai_draft="Unsupported draft",
    )
    rejected = service.reject_email_draft(
        draft_id=draft["id"], reviewer="support-1", reason="Needs more evidence"
    )

    assert rejected["status"] == "rejected"
    with pytest.raises(BusinessRuleError):
        service.send_approved_email(draft_id=draft["id"], sender="support-1")


def test_approve_email_draft_without_edit_uses_llm_draft() -> None:
    service = make_service()
    draft = service.create_email_draft(
        ticket_id="ticket-1",
        customer_id="customer-1",
        ai_draft="Original AI drafted response.",
    )
    approved = service.approve_email_draft(
        draft_id=draft["id"],
        reviewer="support-1",
        edited_body=None,
    )
    sent = service.send_approved_email(draft_id=approved["id"], sender="support-1")
    assert sent["status"] == "sent"
    assert sent["final_sent_message"] == "Original AI drafted response."


def test_create_ticket_persists_in_database() -> None:
    service = make_service()
    ticket = service.create_ticket(
        CustomerIdentity("customer-1"),
        title="New Billing Question",
        description="I have a question about invoice #100.",
    )
    assert ticket["id"].startswith("ticket-")
    assert ticket["customer_id"] == "customer-1"


def test_infer_required_skill_matches_keywords() -> None:
    from services.operations import infer_required_skill

    assert infer_required_skill("I want to make a job lock for my AC repair") == "HVAC"
    assert (
        infer_required_skill("Please fix the leaking toilet in bathroom") == "plumber"
    )
    assert infer_required_skill("Main circuit breaker keeps tripping") == "electrical"
    assert infer_required_skill("Can you inspect my equipment?") == "technician"
    assert infer_required_skill("Hello, what are your opening hours?") is None


def test_create_job_for_ticket_auto_assigns_engineer() -> None:
    service = make_service()
    result = service.create_job_for_ticket(
        CustomerIdentity("customer-1"),
        ticket_id="ticket-1",
        title="Fix AC Unit",
        description="Customer requested an HVAC service job for ticket-1.",
        required_skill="HVAC",
        service_area="London",
    )

    ticket = result["ticket"]
    job = result["job"]
    assert ticket["job_id"] == job["id"]
    assert ticket["assigned_engineer_id"] == "engineer-6"
    assert ticket["status"] == "in_progress"
    assert job["assigned_engineer_id"] == "engineer-6"
    assert job["status"] == "scheduled"


def test_create_job_for_ticket_escalates_when_unassignable() -> None:
    service = make_service()
    # Mark all engineers as max workload or inactive for a rare skill/area combination
    service.connection.execute("UPDATE engineers SET active = 0")
    service.connection.commit()

    result = service.create_job_for_ticket(
        CustomerIdentity("customer-1"),
        ticket_id="ticket-1",
        title="Fix Plumbing",
        description="Customer requested plumbing job for ticket-1.",
        required_skill="plumber",
        service_area="UnknownLocation",
    )

    ticket = result["ticket"]
    assert ticket["needs_escalation"] == 1
    assert ticket["status"] == "escalated"
    assert "No eligible engineer available" in ticket["escalation_reason"]

    escalation = service.connection.execute(
        "SELECT * FROM escalations WHERE ticket_id = ?", ("ticket-1",)
    ).fetchone()
    assert escalation is not None
    assert escalation["status"] == "open"


def test_billing_dispute_ticket_escalates_and_prevents_job_creation():
    from src.services.operations import infer_required_skill

    service = make_service()

    # Skill inference returns None for billing disputes
    assert infer_required_skill("i have a billing issue got charged twice") is None

    ticket = service.create_ticket(
        CustomerIdentity("customer-1"),
        title="Double charge",
        description="i have a billing issue got charged twice",
    )
    assert ticket["needs_escalation"] == 1
    assert ticket["status"] == "escalated"
    assert (
        "billing dispute" in ticket["escalation_reason"].lower()
        or "financial" in ticket["escalation_reason"].lower()
    )
