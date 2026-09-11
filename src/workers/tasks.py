"""Asynchronous ticket processing and notification tasks."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from celery import Task

from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from ml.classifier import TicketClassifier
from rules.escalation_engine import EscalationEngine
from workers.celery_app import celery_app

DATABASE_PATH = Path(__file__).parents[2] / "db" / "helpdesk.sqlite3"


def _repository() -> (
    tuple[HelpdeskDataRepository, sqlite3.Connection, sqlite3.Connection]
):
    sql = sqlite3.connect(DATABASE_PATH)
    transcripts = sqlite3.connect(DATABASE_PATH)
    _ensure_processed_status(sql)
    return HelpdeskDataRepository(sql, NoSQLClient(transcripts)), sql, transcripts


def _ensure_processed_status(connection: sqlite3.Connection) -> None:
    """Upgrade older SQLite files whose ticket constraint lacks ``processed``."""

    definition = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tickets'"
    ).fetchone()
    if definition is None or "'processed'" in definition[0]:
        return
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("ALTER TABLE tickets RENAME TO tickets_legacy")
    connection.executescript(
        """CREATE TABLE tickets (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL CHECK (priority IN (
                'low', 'medium', 'high', 'urgent'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'open', 'in_progress', 'escalated', 'resolved', 'closed', 'processed'
            )),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
        );
        INSERT INTO tickets SELECT * FROM tickets_legacy;
        DROP TABLE tickets_legacy;
        CREATE INDEX IF NOT EXISTS idx_tickets_category ON tickets (category);
        CREATE INDEX IF NOT EXISTS idx_tickets_customer_id ON tickets (customer_id);
        """
    )
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")


class RetryingTask(Task):
    """Base task with bounded exponential retry delays."""

    autoretry_for = (sqlite3.OperationalError, ConnectionError)
    retry_backoff = True
    retry_backoff_max = 60
    max_retries = 3


@celery_app.task(
    bind=True, base=RetryingTask, name="workers.tasks.process_ticket_async"
)
def process_ticket_async(self: RetryingTask, ticket_id: str) -> dict[str, Any]:
    """Classify, route, and mark a stored ticket as processed."""

    repository, sql, transcripts = _repository()
    try:
        context = repository.get_complete_ticket_context(ticket_id)
        if context is None:
            raise ValueError(f"Ticket not found: {ticket_id}")
        ticket = context["ticket"]
        prediction = TicketClassifier().predict(
            f"{ticket['title']}. {ticket['description']}"
        )
        decision = EscalationEngine().evaluate_ticket_rules(
            context,
            {
                "category": prediction.category,
                "priority": prediction.priority,
                "confidence_score": prediction.confidence_score,
            },
        )
        sql.execute(
            "UPDATE tickets SET status = 'processed' WHERE id = ?", (ticket_id,)
        )
        sql.commit()
        return {
            "ticket_id": ticket_id,
            "category": prediction.category,
            "priority": prediction.priority,
            "queue": decision.target_queue,
            "should_escalate": decision.should_escalate,
        }
    finally:
        sql.close()
        transcripts.close()


@celery_app.task(
    bind=True,
    base=RetryingTask,
    name="workers.tasks.send_customer_notification_task",
)
def send_customer_notification_task(
    self: RetryingTask, customer_id: str, message: str
) -> dict[str, str]:
    """Simulate an outbound customer notification."""

    if not customer_id or not message:
        raise ValueError("customer_id and message are required")
    return {"customer_id": customer_id, "status": "sent", "message": message}
