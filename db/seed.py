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
    ticket_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(tickets)")
    }
    migrations = {
        "confidence": "ALTER TABLE tickets ADD COLUMN confidence REAL "
        "CHECK (confidence >= 0.0 AND confidence <= 1.0)",
        "needs_escalation": "ALTER TABLE tickets ADD COLUMN needs_escalation "
        "INTEGER CHECK (needs_escalation IN (0, 1))",
        "assigned_engineer_id": (
            "ALTER TABLE tickets ADD COLUMN assigned_engineer_id TEXT"
        ),
        "job_id": "ALTER TABLE tickets ADD COLUMN job_id TEXT",
        "escalation_reason": "ALTER TABLE tickets ADD COLUMN escalation_reason TEXT",
    }
    for column, statement in migrations.items():
        if column not in ticket_columns:
            connection.execute(statement)
    customer_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(customers)")
    }
    if "verification_status" not in customer_columns:
        connection.execute(
            "ALTER TABLE customers ADD COLUMN verification_status "
            "TEXT NOT NULL DEFAULT 'verified'"
        )
    job_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
    for column, statement in {
        "service_area": "ALTER TABLE jobs ADD COLUMN service_area TEXT",
        "required_skill": "ALTER TABLE jobs ADD COLUMN required_skill TEXT",
    }.items():
        if column not in job_columns:
            connection.execute(statement)
    invoice_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(invoices)")
    }
    invoice_migrations = {
        "subtotal": (
            "ALTER TABLE invoices ADD COLUMN subtotal NUMERIC NOT NULL DEFAULT 0"
        ),
        "tax": "ALTER TABLE invoices ADD COLUMN tax NUMERIC NOT NULL DEFAULT 0",
        "total": "ALTER TABLE invoices ADD COLUMN total NUMERIC NOT NULL DEFAULT 0",
    }
    for column, statement in invoice_migrations.items():
        if column not in invoice_columns:
            connection.execute(statement)


def seed_database(connection: sqlite3.Connection) -> None:
    """Replace existing rows with deterministic relational sample data."""

    initialize_database(connection)
    connection.execute("DELETE FROM sent_emails")
    connection.execute("DELETE FROM email_drafts")
    connection.execute("DELETE FROM invoices")
    connection.execute("DELETE FROM engineer_skills")
    connection.execute("DELETE FROM engineers")
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

    engineers = [
        (
            "engineer-1",
            "Marie Curie",
            "marie@example.com",
            "+44-20-5555-0201",
            1,
            "London",
            1,
        ),
        (
            "engineer-2",
            "Nikola Tesla",
            "nikola@example.com",
            "+1-212-555-0202",
            1,
            "New York",
            2,
        ),
        (
            "engineer-3",
            "Rosalind Franklin",
            "rosalind@example.com",
            "+44-20-5555-0203",
            1,
            "London",
            0,
        ),
        (
            "engineer-4",
            "Thomas Edison",
            "edison@example.com",
            "+1-212-555-0204",
            1,
            "New York",
            0,
        ),
        (
            "engineer-5",
            "Hedy Lamarr",
            "hedy@example.com",
            "+1-312-555-0205",
            1,
            "Chicago",
            1,
        ),
        (
            "engineer-6",
            "James Watt",
            "watt@example.com",
            "+44-20-5555-0206",
            1,
            "London",
            0,
        ),
        (
            "engineer-7",
            "Linus Pauling",
            "linus@example.com",
            "+1-415-555-0207",
            1,
            "San Francisco",
            0,
        ),
        (
            "engineer-8",
            "Chien-Shiung Wu",
            "wu@example.com",
            "+1-206-555-0208",
            1,
            "Seattle",
            1,
        ),
    ]
    connection.executemany(
        """INSERT INTO engineers
        (id, name, email, phone, active, service_area, current_workload)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        engineers,
    )
    connection.executemany(
        "INSERT INTO engineer_skills (engineer_id, skill) VALUES (?, ?)",
        [
            ("engineer-1", "technician"),
            ("engineer-1", "HVAC"),
            ("engineer-2", "electrical"),
            ("engineer-2", "technician"),
            ("engineer-3", "plumber"),
            ("engineer-3", "sanitary"),
            ("engineer-4", "electrical"),
            ("engineer-4", "HVAC"),
            ("engineer-5", "technician"),
            ("engineer-5", "electrical"),
            ("engineer-6", "plumber"),
            ("engineer-6", "HVAC"),
            ("engineer-7", "sanitary"),
            ("engineer-7", "plumber"),
            ("engineer-8", "technician"),
            ("engineer-8", "HVAC"),
        ],
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
        assigned_engineer_id, scheduled_at, service_area, required_skill)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (*job, "London" if i % 2 else "New York", "HVAC")
            for i, job in enumerate(jobs, 1)
        ],
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
        (id, customer_id, job_id, amount, status, due_date, subtotal, tax, total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                *invoice,
                invoice[3],
                round(float(invoice[3]) * 0.2, 2),
                round(float(invoice[3]) * 1.2, 2),
            )
            for invoice in invoices
        ],
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
