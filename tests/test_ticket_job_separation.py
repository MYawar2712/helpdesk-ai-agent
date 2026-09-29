"""Ticket/Job separation: tickets are always created; jobs only when needed.

These tests exercise the additive intent/handled_by/resolution columns and the
operations that either resolve a ticket as the agent (no new Job) or link a
ticket to a real Job (new service request / cancellation).
"""

from __future__ import annotations

import sqlite3

import pytest

from db.seed import seed_database
from models import TicketIntent
from services.operations import (
    AuthorizationError,
    CustomerIdentity,
    HelpdeskOperationsService,
)


def make_service() -> HelpdeskOperationsService:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    return HelpdeskOperationsService(connection)


def _create_ticket(
    service: HelpdeskOperationsService,
    intent: TicketIntent,
    description: str,
    customer_id: str = "customer-1",
) -> dict:
    return service.create_ticket(
        CustomerIdentity(customer_id),
        title=description[:40],
        description=description,
        intent=intent.value,
    )


def _fetch_ticket(service: HelpdeskOperationsService, ticket_id: str) -> dict:
    row = service.connection.execute(
        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
    ).fetchone()
    assert row is not None
    return dict(row)


def _fetch_job(service: HelpdeskOperationsService, job_id: str) -> dict:
    row = service.connection.execute(
        "SELECT * FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert row is not None
    return dict(row)


def _count_jobs(service: HelpdeskOperationsService) -> int:
    return service.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def _draft_approve_send(
    service: HelpdeskOperationsService, ticket: dict, customer_id: str = "customer-1"
) -> dict:
    draft = service.create_email_draft(
        ticket_id=ticket["id"], customer_id=customer_id, ai_draft="Draft reply."
    )
    approved = service.approve_email_draft(draft_id=draft["id"], reviewer="support-1")
    return service.send_approved_email(draft_id=approved["id"], sender="support-1")


# ---------------------------------------------------------------------------
# Agent-only intents: a ticket is created but never a new Job.
# ---------------------------------------------------------------------------


def test_general_inquiry_creates_ticket_not_job() -> None:
    service = make_service()
    before = _count_jobs(service)
    ticket = _create_ticket(
        service, TicketIntent.GENERAL_INQUIRY, "What are your opening hours?"
    )

    _ = _draft_approve_send(service, ticket)

    final = _fetch_ticket(service, ticket["id"])
    assert _count_jobs(service) == before
    assert final["job_id"] is None
    assert final["related_job_id"] is None


def test_non_job_reply_does_not_repeat_an_existing_job_id() -> None:
    service = make_service()
    existing_job = service.create_job(
        CustomerIdentity("customer-1"),
        title="AC repair",
        description="Existing AC repair appointment.",
        required_skill="HVAC",
        service_area="London",
    )
    ticket = _create_ticket(
        service,
        TicketIntent.BILLING_INQUIRY,
        "I was charged twice for my invoice.",
    )

    sent = _draft_approve_send(service, ticket)

    assert existing_job["id"] not in sent["final_sent_message"]


def test_job_status_creates_ticket_not_job() -> None:
    service = make_service()
    before = _count_jobs(service)
    ticket = _create_ticket(
        service, TicketIntent.JOB_STATUS, "What's the status of job-6?"
    )

    _ = _draft_approve_send(service, ticket)

    final = _fetch_ticket(service, ticket["id"])
    assert _count_jobs(service) == before
    assert final["job_id"] is None
    assert final["related_job_id"] is None


def test_billing_inquiry_creates_ticket_not_job() -> None:
    service = make_service()
    before = _count_jobs(service)
    ticket = _create_ticket(
        service,
        TicketIntent.BILLING_INQUIRY,
        "Can you help me understand my recent invoice?",
    )

    _draft_approve_send(service, ticket)

    final = _fetch_ticket(service, ticket["id"])
    assert _count_jobs(service) == before
    assert final["job_id"] is None
    assert final["related_job_id"] is None


def test_cancel_job_creates_ticket_and_cancels_existing_job() -> None:
    service = make_service()
    before = _count_jobs(service)
    ticket = _create_ticket(
        service, TicketIntent.CANCEL_JOB, "Please cancel my job job-6"
    )

    result = service.cancel_job_for_ticket("customer-1", ticket["id"], job_id="job-6")

    final = _fetch_ticket(service, ticket["id"])
    job6 = _fetch_job(service, "job-6")
    assert _count_jobs(service) == before  # no new job created
    assert job6["status"] == "cancelled"
    assert [j["id"] for j in result["cancelled_jobs"]] == ["job-6"]
    assert final["status"] == "resolved"
    assert final["handled_by"] == "AI_AGENT"


# ---------------------------------------------------------------------------
# Cancel job behaviour.
# ---------------------------------------------------------------------------


def test_cancel_job_updates_existing_job_status_to_cancelled() -> None:
    service = make_service()

    cancelled = service.cancel_customer_scheduled_jobs("customer-1", job_id="job-6")

    assert [j["id"] for j in cancelled] == ["job-6"]
    assert _fetch_job(service, "job-6")["status"] == "cancelled"


def test_cancel_job_links_ticket_related_job_id() -> None:
    service = make_service()
    ticket = _create_ticket(
        service, TicketIntent.CANCEL_JOB, "Please cancel my scheduled job"
    )

    result = service.cancel_job_for_ticket("customer-1", ticket["id"])

    assert result["cancelled_jobs"], "expected at least one cancelled job"
    final = _fetch_ticket(service, ticket["id"])
    cancelled_ids = {j["id"] for j in result["cancelled_jobs"]}
    assert final["related_job_id"] in cancelled_ids


def test_cancel_specific_job_id() -> None:
    service = make_service()

    cancelled = service.cancel_customer_scheduled_jobs("customer-1", job_id="job-6")

    assert [j["id"] for j in cancelled] == ["job-6"]
    # Other customers' jobs are untouched.
    assert _fetch_job(service, "job-4")["status"] == "scheduled"


def test_cancel_job_wrong_customer_raises_authorization_error() -> None:
    service = make_service()

    with pytest.raises(AuthorizationError):
        service.cancel_customer_scheduled_jobs("customer-2", job_id="job-6")

    assert _fetch_job(service, "job-6")["status"] == "scheduled"


# ---------------------------------------------------------------------------
# New service request: a ticket AND a job are created and linked.
# ---------------------------------------------------------------------------


def test_new_service_request_creates_ticket_and_job() -> None:
    service = make_service()
    before = _count_jobs(service)
    ticket = _create_ticket(
        service,
        TicketIntent.NEW_SERVICE_REQUEST,
        "My boiler is broken, please book an engineer",
    )

    sent = _draft_approve_send(service, ticket)

    final = _fetch_ticket(service, ticket["id"])
    assert _count_jobs(service) == before + 1
    assert final["job_id"] is not None
    assert final["related_job_id"] == final["job_id"]
    assert final["job_id"] in sent["final_sent_message"]


def test_new_service_request_links_ticket_related_job_id() -> None:
    service = make_service()
    ticket = _create_ticket(
        service, TicketIntent.NEW_SERVICE_REQUEST, "My boiler is broken"
    )
    job = service.create_job(
        CustomerIdentity("customer-1"),
        title="Boiler repair",
        description="Fix the broken boiler",
        required_skill="HVAC",
        service_area="London",
    )

    linked = service.link_ticket_to_job(ticket["id"], job["id"])

    assert linked["related_job_id"] == job["id"]


# ---------------------------------------------------------------------------
# Data isolation / ownership.
# ---------------------------------------------------------------------------


def test_cancel_job_cannot_cancel_another_customers_job() -> None:
    service = make_service()
    # customer-2's own ticket, but they try to cancel customer-1's job-6.
    ticket = _create_ticket(
        service,
        TicketIntent.CANCEL_JOB,
        "Please cancel job-6",
        customer_id="customer-2",
    )

    with pytest.raises(AuthorizationError):
        service.cancel_job_for_ticket("customer-2", ticket["id"], job_id="job-6")

    assert _fetch_job(service, "job-6")["status"] == "scheduled"


def test_update_job_status_enforces_ownership() -> None:
    service = make_service()

    with pytest.raises(AuthorizationError):
        service.update_customer_job_status(
            CustomerIdentity("customer-2"), "job-6", "cancelled"
        )

    assert _fetch_job(service, "job-6")["status"] == "scheduled"


# ---------------------------------------------------------------------------
# Ticket resolution.
# ---------------------------------------------------------------------------


def test_resolve_ticket_as_agent_sets_status_resolved() -> None:
    service = make_service()
    ticket = _create_ticket(
        service, TicketIntent.GENERAL_INQUIRY, "What are your opening hours?"
    )

    resolved = service.resolve_ticket_as_agent(ticket["id"], "Provided opening hours.")

    assert resolved["status"] == "resolved"
    assert resolved["handled_by"] == "AI_AGENT"
    assert resolved["resolution"] == "Provided opening hours."


def test_agent_only_ticket_has_null_related_job_id() -> None:
    service = make_service()
    ticket = _create_ticket(
        service, TicketIntent.JOB_STATUS, "What's the status of job-6?"
    )

    resolved = service.resolve_ticket_as_agent(ticket["id"], "Job-6 is scheduled.")

    assert resolved["related_job_id"] is None
    assert resolved["job_id"] is None
