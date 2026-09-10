from helpdesk_ai_agent.ticket import Priority, Ticket


def test_ticket_has_typed_defaults() -> None:
    ticket = Ticket("HD-1", "Cannot sign in", "user@example.com")

    assert ticket.priority is Priority.NORMAL
    assert ticket.resolved is False


def test_resolve_returns_a_new_resolved_ticket() -> None:
    ticket = Ticket("HD-2", "Reset password", "user@example.com", Priority.HIGH)

    resolved = ticket.resolve()

    assert resolved.resolved is True
    assert ticket.resolved is False
    assert resolved.priority is Priority.HIGH
