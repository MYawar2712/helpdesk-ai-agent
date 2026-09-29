import sqlite3

import pytest

from db.queries import (
    get_high_value_disputed_customers,
    get_jobs_per_engineer,
    get_overdue_invoices,
    get_tickets_by_category,
)
from db.seed import initialize_database, seed_database


def test_schema_and_seed_create_integrity_checked_database() -> None:
    connection = sqlite3.connect(":memory:")

    seed_database(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("customers", "jobs", "invoices", "tickets")
    }

    assert {
        "customers",
        "jobs",
        "invoices",
        "tickets",
        "engineers",
        "engineer_skills",
        "ticket_messages",
        "email_drafts",
        "sent_emails",
        "escalations",
        "audit_log",
    } <= tables
    assert counts == {"customers": 5, "jobs": 10, "invoices": 10, "tickets": 10}
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_seed_rejects_orphaned_foreign_keys() -> None:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)

    try:
        connection.execute(
            "INSERT INTO jobs (id, customer_id, title, description, status, priority) "
            "VALUES ('bad', 'missing', 'Bad', 'Bad', 'pending', 'low')"
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("foreign-key violation was not rejected")


def test_ticket_category_aggregation() -> None:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)

    result = get_tickets_by_category(connection)

    assert result == [
        {"category": "billing", "ticket_count": 3},
        {"category": "general", "ticket_count": 3},
        {"category": "technical", "ticket_count": 4},
    ]


def test_ticket_category_constraint_rejects_legacy_labels() -> None:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)

    with pytest.raises(sqlite3.IntegrityError, match="invalid ticket category"):
        connection.execute(
            "UPDATE tickets SET category = 'hardware' WHERE id = 'ticket-1'"
        )


def test_initialize_database_migrates_legacy_category_labels() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE tickets (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO tickets
            (id, customer_id, title, description, category, priority, status)
        VALUES ('legacy-ticket', 'customer-1', 'Legacy', 'Legacy record',
                'hardware', 'low', 'open')
        """
    )

    initialize_database(connection)

    category = connection.execute(
        "SELECT category FROM tickets WHERE id = 'legacy-ticket'"
    ).fetchone()[0]
    assert category == "technical"


def test_overdue_invoice_join_returns_customer_details() -> None:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)

    result = get_overdue_invoices(connection)

    assert [row["invoice_id"] for row in result] == [
        "invoice-3",
        "invoice-5",
        "invoice-7",
    ]
    assert result[0]["customer_name"] == "Alan Turing"


def test_jobs_per_engineer_aggregation() -> None:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)

    assert get_jobs_per_engineer(connection) == [
        {"engineer_id": "engineer-1", "job_count": 4},
        {"engineer_id": "engineer-2", "job_count": 3},
        {"engineer_id": "engineer-3", "job_count": 3},
    ]


def test_high_value_subquery_returns_expected_customer() -> None:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)

    result = get_high_value_disputed_customers(connection)

    assert result == [
        {
            "customer_id": "customer-5",
            "customer_name": "Dorothy Vaughan",
            "overdue_total": 3200,
        },
        {
            "customer_id": "customer-3",
            "customer_name": "Alan Turing",
            "overdue_total": 2500,
        },
        {
            "customer_id": "customer-2",
            "customer_name": "Grace Hopper",
            "overdue_total": 1750,
        },
    ]
