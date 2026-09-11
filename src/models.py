"""Core domain models for the helpdesk AI agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final


@dataclass(frozen=True, slots=True)
class EscalationResult:
    """Decision produced after applying business rules to a ticket."""

    should_escalate: bool
    target_queue: str
    priority_override: str | None
    requires_human_handoff: bool
    reasons: list[str]


class JobStatus(StrEnum):
    """Lifecycle states for a scheduled customer job."""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TicketStatus(StrEnum):
    """Lifecycle states for a support ticket."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    PROCESSED = "processed"


class TicketPriority(StrEnum):
    """Urgency levels for a support ticket."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class InvoiceStatus(StrEnum):
    """Payment states for an invoice."""

    UNPAID = "unpaid"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


_IMMUTABLE_TYPES: Final[tuple[type[object], ...]] = (str,)


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, _IMMUTABLE_TYPES) or not value:
        raise TypeError(f"{field_name} must be a non-empty string")


def _require_datetime(value: object, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")


def _require_date(value: object, field_name: str) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a date")


@dataclass(slots=True)
class Job:
    """A piece of work scheduled for a customer."""

    id: str
    customer_id: str
    title: str
    description: str
    status: JobStatus
    priority: TicketPriority
    assigned_engineer_id: str | None
    scheduled_at: datetime | None
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("id", "customer_id", "title", "description"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.status, JobStatus):
            raise TypeError("status must be a JobStatus")
        if not isinstance(self.priority, TicketPriority):
            raise TypeError("priority must be a TicketPriority")
        if self.assigned_engineer_id is not None:
            _require_text(self.assigned_engineer_id, "assigned_engineer_id")
        if self.scheduled_at is not None:
            _require_datetime(self.scheduled_at, "scheduled_at")
        _require_datetime(self.created_at, "created_at")


@dataclass(slots=True)
class Customer:
    """A customer who owns jobs, invoices, and support tickets."""

    id: str
    name: str
    email: str
    phone: str
    company: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("id", "name", "email", "phone", "company"):
            _require_text(getattr(self, name), name)
        _require_datetime(self.created_at, "created_at")


@dataclass(slots=True)
class Invoice:
    """An amount owed by a customer for a job."""

    id: str
    customer_id: str
    job_id: str
    amount: Decimal
    status: InvoiceStatus
    due_date: date
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("id", "customer_id", "job_id"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be a Decimal")
        if self.amount < Decimal("0"):
            raise ValueError("amount must not be negative")
        if not isinstance(self.status, InvoiceStatus):
            raise TypeError("status must be an InvoiceStatus")
        _require_date(self.due_date, "due_date")
        _require_datetime(self.created_at, "created_at")

    @property
    def is_overdue(self) -> bool:
        """Return whether payment is overdue as of today."""

        return self.status is InvoiceStatus.OVERDUE or (
            self.status is InvoiceStatus.UNPAID and self.due_date < date.today()
        )


@dataclass(slots=True)
class Ticket:
    """A customer support request."""

    id: str
    customer_id: str
    title: str
    description: str
    category: str
    priority: TicketPriority
    status: TicketStatus
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("id", "customer_id", "title", "description", "category"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.priority, TicketPriority):
            raise TypeError("priority must be a TicketPriority")
        if not isinstance(self.status, TicketStatus):
            raise TypeError("status must be a TicketStatus")
        _require_datetime(self.created_at, "created_at")

    @property
    def can_escalate(self) -> bool:
        """Return whether the ticket is active and high enough priority."""

        return self.status in {
            TicketStatus.OPEN,
            TicketStatus.IN_PROGRESS,
        } and self.priority in {TicketPriority.HIGH, TicketPriority.URGENT}
