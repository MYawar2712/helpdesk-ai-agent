"""Unified access to relational helpdesk data and JSON transcripts."""

from __future__ import annotations

import sqlite3
from typing import Any

from clients.nosql_client import NoSQLClient
from db.sqlite_guard import serialize_connection
from llm.structured_extract import TicketClassification


class HelpdeskDataRepository:
    """Combine SQL domain records with NoSQL transcript documents."""

    def __init__(
        self, sql_connection: sqlite3.Connection, nosql_client: NoSQLClient
    ) -> None:
        # The connection is shared by every request thread, so it is wrapped in
        # a serialising proxy. ``sql_connection`` stays the single access point
        # for callers, so no other module has to change.
        self.sql_connection = serialize_connection(sql_connection)
        self.nosql_client = nosql_client
        self.sql_connection.row_factory = sqlite3.Row

    def get_complete_ticket_context(self, ticket_id: str) -> dict[str, Any] | None:
        """Return a ticket, customer, related jobs, invoices, and transcripts."""

        ticket = self._one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if ticket is None:
            return None
        customer = self._one(
            "SELECT * FROM customers WHERE id = ?", (ticket["customer_id"],)
        )
        jobs = self._many(
            "SELECT * FROM jobs WHERE customer_id = ? ORDER BY created_at, id",
            (ticket["customer_id"],),
        )
        invoices = self._many(
            """SELECT * FROM invoices
            WHERE customer_id = ? AND status IN ('unpaid', 'overdue')
            ORDER BY due_date, id""",
            (ticket["customer_id"],),
        )
        return {
            "ticket": ticket,
            "customer": customer,
            "jobs": jobs,
            "open_invoices": invoices,
            "transcripts": self.nosql_client.get_transcripts_by_ticket(ticket_id),
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return one job by ID, or latest job for customer_id."""

        job = self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job is None:
            job = self._one(
                "SELECT * FROM jobs WHERE customer_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (job_id,),
            )
        return job

    def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        """Return one customer by ID."""

        return self._one("SELECT * FROM customers WHERE id = ?", (customer_id,))

    def get_open_invoices(self, customer_id: str) -> list[dict[str, Any]]:
        """Return a customer's unpaid or overdue invoices."""

        return self._many(
            """SELECT * FROM invoices
            WHERE customer_id = ? AND status IN ('unpaid', 'overdue')
            ORDER BY due_date, id""",
            (customer_id,),
        )

    def get_all_invoices(self, customer_id: str) -> list[dict[str, Any]]:
        """Return all invoices (paid, unpaid, overdue) for a customer."""

        return self._many(
            "SELECT * FROM invoices WHERE customer_id = ? ORDER BY due_date, id",
            (customer_id,),
        )

    def get_customer_overview(self, customer_id: str) -> dict[str, Any] | None:
        """Return a customer profile with jobs, invoices, and chat history."""

        customer = self._one("SELECT * FROM customers WHERE id = ?", (customer_id,))
        if customer is None:
            return None
        jobs = self._many(
            "SELECT * FROM jobs WHERE customer_id = ? ORDER BY created_at, id",
            (customer_id,),
        )
        invoices = self._many(
            "SELECT * FROM invoices WHERE customer_id = ? ORDER BY due_date, id",
            (customer_id,),
        )
        transcripts = self.nosql_client.get_transcripts_by_customer(customer_id)
        return {
            "customer": customer,
            "jobs": jobs,
            "invoices": invoices,
            "transcripts": transcripts,
        }

    def list_tickets(
        self,
        *,
        status: str | None = None,
        intent: str | None = None,
        handled_by: str | None = None,
        customer_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return tickets ordered by creation time, with optional filters."""

        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if intent:
            conditions.append("intent = ?")
            params.append(intent)
        if handled_by:
            conditions.append("handled_by = ?")
            params.append(handled_by)
        if customer_id:
            conditions.append("customer_id = ?")
            params.append(customer_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = (
            f"SELECT * FROM tickets{where} ORDER BY created_at DESC, id DESC LIMIT ?"
        )
        params.append(limit)
        return self._many(query, tuple(params))

    def list_jobs(
        self,
        *,
        status: str | None = None,
        customer_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return jobs ordered by creation time, with optional filters."""

        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if customer_id:
            conditions.append("customer_id = ?")
            params.append(customer_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM jobs{where} ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return self._many(query, tuple(params))

    def list_customers(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return customers ordered by creation time."""

        return self._many(
            "SELECT * FROM customers ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )

    def list_email_drafts(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return email drafts ordered by creation time, with optional status filter."""

        if status:
            return self._many(
                "SELECT * FROM email_drafts WHERE status = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (status, limit),
            )
        return self._many(
            "SELECT * FROM email_drafts ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )

    def save_ticket_classification(
        self, ticket_id: str, classification: TicketClassification
    ) -> None:
        """Persist a validated LLM classification for an existing ticket."""

        cursor = self.sql_connection.execute(
            """UPDATE tickets
            SET category = ?, priority = ?, confidence = ?, needs_escalation = ?
            WHERE id = ?""",
            (
                classification.category,
                classification.priority,
                classification.confidence,
                int(classification.needs_escalation),
                ticket_id,
            ),
        )
        if cursor.rowcount != 1:
            self.sql_connection.rollback()
            raise LookupError(f"Ticket does not exist: {ticket_id}")
        self.sql_connection.commit()

    def _one(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self.sql_connection.execute(query, parameters).fetchone()
        return dict(row) if row is not None else None

    def _many(self, query: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
        return [dict(row) for row in self.sql_connection.execute(query, parameters)]
