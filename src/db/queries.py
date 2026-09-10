"""Raw SQL query helpers for the helpdesk SQLite database."""

from __future__ import annotations

import sqlite3
from typing import Any

Row = dict[str, Any]


def _rows(connection: sqlite3.Connection, query: str) -> list[Row]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query).fetchall()]


def get_tickets_by_category(connection: sqlite3.Connection) -> list[Row]:
    """Count support tickets grouped by category."""

    return _rows(
        connection,
        """SELECT category, COUNT(*) AS ticket_count
        FROM tickets
        GROUP BY category
        ORDER BY category""",
    )


def get_overdue_invoices(connection: sqlite3.Connection) -> list[Row]:
    """Return overdue invoices joined with their customer details."""

    return _rows(
        connection,
        """SELECT invoices.id AS invoice_id, invoices.amount, invoices.status,
            invoices.due_date, customers.id AS customer_id,
            customers.name AS customer_name, customers.email AS customer_email
        FROM invoices
        JOIN customers ON customers.id = invoices.customer_id
        WHERE invoices.status IN ('unpaid', 'overdue')
            AND invoices.due_date < DATE('now')
        ORDER BY invoices.due_date, invoices.id""",
    )


def get_jobs_per_engineer(connection: sqlite3.Connection) -> list[Row]:
    """Count jobs assigned to each field engineer."""

    return _rows(
        connection,
        """SELECT assigned_engineer_id AS engineer_id, COUNT(*) AS job_count
        FROM jobs
        WHERE assigned_engineer_id IS NOT NULL
        GROUP BY assigned_engineer_id
        ORDER BY assigned_engineer_id""",
    )


def get_high_value_disputed_customers(connection: sqlite3.Connection) -> list[Row]:
    """Find customers with overdue invoices above the average invoice amount."""

    return _rows(
        connection,
        """SELECT customers.id AS customer_id, customers.name AS customer_name,
            SUM(invoices.amount) AS overdue_total
        FROM customers
        JOIN invoices ON invoices.customer_id = customers.id
        WHERE invoices.status = 'overdue'
            AND invoices.amount > (SELECT AVG(amount) FROM invoices)
        GROUP BY customers.id, customers.name
        ORDER BY overdue_total DESC""",
    )
