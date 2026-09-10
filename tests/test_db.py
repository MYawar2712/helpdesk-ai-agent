import sqlite3

from db.queries import (
    get_high_value_disputed_customers,
    get_jobs_per_engineer,
    get_overdue_invoices,
    get_tickets_by_category,
)
from db.seed import seed_database


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

    assert tables == {"customers", "jobs", "invoices", "tickets"}
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
        {"category": "access", "ticket_count": 3},
        {"category": "billing", "ticket_count": 3},
        {"category": "hardware", "ticket_count": 2},
        {"category": "network", "ticket_count": 2},
    ]


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
