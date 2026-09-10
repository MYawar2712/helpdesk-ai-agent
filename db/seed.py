"""Seed a local SQLite database with deterministic helpdesk data."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

DATABASE_PATH = Path(__file__).with_name("helpdesk.sqlite3")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the schema and enable foreign-key enforcement."""

    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def seed_database(connection: sqlite3.Connection) -> None:
    """Replace existing rows with deterministic relational sample data."""

    initialize_database(connection)
    connection.execute("DELETE FROM invoices")
    connection.execute("DELETE FROM tickets")
    connection.execute("DELETE FROM jobs")
    connection.execute("DELETE FROM customers")

    customers = [
        (
            "customer-1",
            "Ada Lovelace",
            "ada@example.com",
            "+44-20-5555-0101",
            "Analytical Engines",
        ),
        (
            "customer-2",
            "Grace Hopper",
            "grace@example.com",
            "+1-212-555-0102",
            "Compiler Works",
        ),
        (
            "customer-3",
            "Alan Turing",
            "alan@example.com",
            "+44-20-5555-0103",
            "Universal Machines",
        ),
        (
            "customer-4",
            "Katherine Johnson",
            "katherine@example.com",
            "+1-212-555-0104",
            "Orbital Systems",
        ),
        (
            "customer-5",
            "Dorothy Vaughan",
            "dorothy@example.com",
            "+1-212-555-0105",
            "Launch Operations",
        ),
    ]
    connection.executemany(
        "INSERT INTO customers (id, name, email, phone, company) "
        "VALUES (?, ?, ?, ?, ?)",
        customers,
    )

    jobs = [
        (
            f"job-{number}",
            f"customer-{(number - 1) % 5 + 1}",
            f"Service visit {number}",
            "Inspect and maintain customer equipment",
            "completed" if number <= 3 else "scheduled",
            "high" if number % 3 == 0 else "medium",
            f"engineer-{(number - 1) % 3 + 1}",
            (date.today() + timedelta(days=number)).isoformat(),
        )
        for number in range(1, 11)
    ]
    connection.executemany(
        """INSERT INTO jobs
        (id, customer_id, title, description, status, priority,
        assigned_engineer_id, scheduled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        jobs,
    )

    invoices = [
        (
            f"invoice-{number}",
            f"customer-{(number - 1) % 5 + 1}",
            f"job-{number}",
            amount,
            status,
            due_date,
        )
        for number, amount, status, due_date in [
            (1, 1250.00, "paid", date.today().isoformat()),
            (2, 800.00, "unpaid", (date.today() + timedelta(days=10)).isoformat()),
            (3, 2500.00, "overdue", (date.today() - timedelta(days=20)).isoformat()),
            (4, 450.00, "paid", date.today().isoformat()),
            (5, 3200.00, "overdue", (date.today() - timedelta(days=15)).isoformat()),
            (6, 600.00, "unpaid", (date.today() + timedelta(days=5)).isoformat()),
            (7, 1750.00, "overdue", (date.today() - timedelta(days=8)).isoformat()),
            (8, 900.00, "cancelled", date.today().isoformat()),
            (9, 2100.00, "paid", date.today().isoformat()),
            (10, 700.00, "unpaid", (date.today() + timedelta(days=30)).isoformat()),
        ]
    ]
    connection.executemany(
        """INSERT INTO invoices
        (id, customer_id, job_id, amount, status, due_date)
        VALUES (?, ?, ?, ?, ?, ?)""",
        invoices,
    )

    tickets = [
        (
            f"ticket-{number}",
            f"customer-{(number - 1) % 5 + 1}",
            f"Support request {number}",
            "Customer needs help with a service",
            category,
            priority,
            status,
        )
        for number, category, priority, status in [
            (1, "access", "high", "open"),
            (2, "billing", "medium", "in_progress"),
            (3, "hardware", "urgent", "escalated"),
            (4, "access", "low", "resolved"),
            (5, "network", "high", "open"),
            (6, "billing", "urgent", "escalated"),
            (7, "hardware", "medium", "closed"),
            (8, "network", "low", "open"),
            (9, "access", "medium", "in_progress"),
            (10, "billing", "high", "open"),
        ]
    ]
    connection.executemany(
        """INSERT INTO tickets
        (id, customer_id, title, description, category, priority, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        tickets,
    )
    connection.commit()


def main() -> None:
    """Create and seed the local database file."""

    with sqlite3.connect(DATABASE_PATH) as connection:
        seed_database(connection)
    print(f"Seeded {DATABASE_PATH}")


if __name__ == "__main__":
    main()
