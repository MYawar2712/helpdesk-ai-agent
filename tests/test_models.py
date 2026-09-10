from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from models import (
    Customer,
    Invoice,
    InvoiceStatus,
    Job,
    JobStatus,
    Ticket,
    TicketPriority,
    TicketStatus,
)

NOW = datetime(2026, 1, 15, 10, 30)


def test_job_instantiates_with_typed_values() -> None:
    job = Job(
        id="job-1",
        customer_id="customer-1",
        title="Repair router",
        description="Replace failed hardware",
        status=JobStatus.SCHEDULED,
        priority=TicketPriority.HIGH,
        assigned_engineer_id="engineer-1",
        scheduled_at=NOW + timedelta(days=1),
        created_at=NOW,
    )

    assert job.id == "job-1"
    assert isinstance(job.status, JobStatus)
    assert isinstance(job.scheduled_at, datetime)


def test_job_allows_unassigned_and_unscheduled_work() -> None:
    job = Job(
        "job-2",
        "customer-1",
        "Investigate outage",
        "Review service logs",
        JobStatus.PENDING,
        TicketPriority.MEDIUM,
        None,
        None,
        NOW,
    )

    assert job.assigned_engineer_id is None
    assert job.scheduled_at is None


def test_customer_instantiates_with_typed_values() -> None:
    customer = Customer(
        "customer-1",
        "Ada Lovelace",
        "ada@example.com",
        "+441234567890",
        "Analytical Engines",
        NOW,
    )

    assert customer.name == "Ada Lovelace"
    assert isinstance(customer.created_at, datetime)


def test_invoice_is_not_overdue_when_paid_or_not_yet_due() -> None:
    paid = Invoice(
        "inv-1",
        "customer-1",
        "job-1",
        Decimal("125.00"),
        InvoiceStatus.PAID,
        date.today(),
        NOW,
    )
    upcoming = Invoice(
        "inv-2",
        "customer-1",
        "job-1",
        Decimal("125.00"),
        InvoiceStatus.UNPAID,
        date.today(),
        NOW,
    )

    assert paid.is_overdue is False
    assert upcoming.is_overdue is False


def test_invoice_is_overdue_when_status_or_date_requires_it() -> None:
    marked_overdue = Invoice(
        "inv-3",
        "customer-1",
        "job-1",
        Decimal("50"),
        InvoiceStatus.OVERDUE,
        date.today(),
        NOW,
    )
    past_due = Invoice(
        "inv-4",
        "customer-1",
        "job-1",
        Decimal("50"),
        InvoiceStatus.UNPAID,
        date.today() - timedelta(days=1),
        NOW,
    )

    assert marked_overdue.is_overdue is True
    assert past_due.is_overdue is True


def test_ticket_can_escalate_only_when_active_and_high_priority() -> None:
    urgent = Ticket(
        "ticket-1",
        "customer-1",
        "Service down",
        "No access",
        "outage",
        TicketPriority.URGENT,
        TicketStatus.OPEN,
        NOW,
    )
    low = Ticket(
        "ticket-2",
        "customer-1",
        "Question",
        "How?",
        "general",
        TicketPriority.LOW,
        TicketStatus.OPEN,
        NOW,
    )
    resolved = Ticket(
        "ticket-3",
        "customer-1",
        "Old issue",
        "Done",
        "general",
        TicketPriority.HIGH,
        TicketStatus.RESOLVED,
        NOW,
    )

    assert urgent.can_escalate is True
    assert low.can_escalate is False
    assert resolved.can_escalate is False


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (lambda: Customer("id", "name", "email", "phone", "company", NOW), "name", ""),
        (
            lambda: Job(
                "id",
                "customer",
                "title",
                "description",
                JobStatus.PENDING,
                TicketPriority.LOW,
                None,
                None,
                NOW,
            ),
            "status",
            "pending",
        ),
        (
            lambda: Invoice(
                "id",
                "customer",
                "job",
                Decimal("1"),
                InvoiceStatus.PAID,
                date.today(),
                NOW,
            ),
            "amount",
            1,
        ),
        (
            lambda: Ticket(
                "id",
                "customer",
                "title",
                "description",
                "category",
                TicketPriority.LOW,
                TicketStatus.OPEN,
                NOW,
            ),
            "priority",
            "low",
        ),
    ],
)
def test_models_reject_invalid_field_types(factory, field, value) -> None:
    # Reconstruct each dataclass with one deliberately invalid value.
    model = factory()
    values = {name: getattr(model, name) for name in model.__dataclass_fields__}
    values[field] = value

    with pytest.raises((TypeError, ValueError)):
        type(model)(**values)


def test_invoice_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="negative"):
        Invoice(
            "id",
            "customer",
            "job",
            Decimal("-1"),
            InvoiceStatus.UNPAID,
            date.today(),
            NOW,
        )
