"""Typed domain models used by the helpdesk agent."""

from dataclasses import dataclass
from enum import StrEnum


class Priority(StrEnum):
    """Urgency assigned to a support ticket."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class Ticket:
    """A support request with explicit, typed fields."""

    ticket_id: str
    subject: str
    requester: str
    priority: Priority = Priority.NORMAL
    resolved: bool = False

    def resolve(self) -> "Ticket":
        """Return a resolved copy without mutating the original ticket."""

        return Ticket(
            ticket_id=self.ticket_id,
            subject=self.subject,
            requester=self.requester,
            priority=self.priority,
            resolved=True,
        )
