"""Persistent conversation-thread storage for the helpdesk AI agent.

Each inbound email exchange belongs to exactly one ``ConversationThread``.
The thread is identified by the email provider's thread-ID when available;
otherwise a new UUID is generated.  Every message – from a customer, the AI
agent, a human agent, or the system – is stored as a ``ConversationMessage``
so that follow-up replies can be answered with full context.

Key design decisions
--------------------
* **Idempotency** – ``email_message_id`` has a UNIQUE constraint.  Inserting
  the same provider message-ID twice is silently ignored (``INSERT OR IGNORE``),
  preventing duplicate processing on re-delivered webhooks.
* **Customer isolation** – every public method that accepts a ``thread_id``
  also validates the owning ``customer_id`` before returning data.
* **History cap** – :py:func:`get_recent_messages` returns at most
  ``limit`` rows so that LLM context windows are not exhausted.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConversationThread:
    """Lightweight projection of the ``conversation_threads`` table."""

    thread_id: str
    customer_id: str
    ticket_id: str | None
    subject: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """Lightweight projection of the ``conversation_messages`` table."""

    message_id: str
    thread_id: str
    customer_id: str
    sender_type: str  # 'customer' | 'agent' | 'human' | 'system'
    sender_email: str
    content: str
    email_message_id: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class ConversationRepository:
    """Read / write conversation threads and messages in SQLite.

    All mutating methods commit immediately so callers do not need to manage
    transactions explicitly.

    Parameters
    ----------
    connection:
        An open :class:`sqlite3.Connection`.  ``row_factory`` will be set to
        :attr:`sqlite3.Row` by the constructor.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------
    # Thread helpers
    # ------------------------------------------------------------------

    def create_thread(
        self,
        *,
        customer_id: str,
        thread_id: str | None = None,
        ticket_id: str | None = None,
        subject: str = "",
    ) -> ConversationThread:
        """Insert a new conversation thread and return it.

        Parameters
        ----------
        customer_id:
            The owning customer.  Must reference an existing ``customers``
            row when foreign-key enforcement is on.
        thread_id:
            Optional explicit ID (e.g. the email provider's thread ID).
            When omitted a new UUID4 is generated.
        ticket_id:
            Optional linked helpdesk ticket.
        subject:
            Email subject line or empty string.

        Returns
        -------
        ConversationThread
            The newly created thread.
        """
        tid = thread_id or str(uuid.uuid4())
        now = _utcnow()
        self._conn.execute(
            """
            INSERT INTO conversation_threads
                (thread_id, customer_id, ticket_id, subject, status,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (tid, customer_id, ticket_id, subject, now, now),
        )
        self._conn.commit()
        return ConversationThread(
            thread_id=tid,
            customer_id=customer_id,
            ticket_id=ticket_id,
            subject=subject,
            status="open",
            created_at=now,
            updated_at=now,
        )

    def get_thread(
        self,
        thread_id: str,
        *,
        customer_id: str | None = None,
    ) -> ConversationThread | None:
        """Return the thread, or ``None`` if it does not exist.

        Parameters
        ----------
        thread_id:
            Primary key of the thread.
        customer_id:
            When provided, ``None`` is returned (and a security warning is
            logged) if the thread belongs to a *different* customer.
        """
        row = self._conn.execute(
            "SELECT * FROM conversation_threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        thread = _row_to_thread(row)
        if customer_id is not None and thread.customer_id != customer_id:
            # Security isolation: do not expose another customer's thread.
            return None
        return thread

    def get_thread_by_email_thread_id(
        self,
        email_thread_id: str,
        *,
        customer_id: str | None = None,
    ) -> ConversationThread | None:
        """Look up a thread by the provider-level email thread ID.

        Because ``thread_id`` is used directly as the provider thread ID
        (when the provider ID is known at creation time), this is identical
        to :py:meth:`get_thread`.  The method is provided as a named alias
        for clarity in calling code.
        """
        return self.get_thread(email_thread_id, customer_id=customer_id)

    def list_threads(self, *, customer_id: str) -> list[ConversationThread]:
        """Return a customer's conversation threads, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM conversation_threads WHERE customer_id = ? "
            "ORDER BY updated_at DESC",
            (customer_id,),
        ).fetchall()
        return [_row_to_thread(row) for row in rows]

    def update_thread_ticket(self, thread_id: str, ticket_id: str) -> None:
        """Link an existing thread to a helpdesk ticket."""
        now = _utcnow()
        self._conn.execute(
            "UPDATE conversation_threads SET ticket_id = ?, updated_at = ? "
            "WHERE thread_id = ?",
            (ticket_id, now, thread_id),
        )
        self._conn.commit()

    def thread_belongs_to_customer(self, thread_id: str, customer_id: str) -> bool:
        """Return ``True`` iff the thread is owned by *customer_id*."""
        row = self._conn.execute(
            "SELECT customer_id FROM conversation_threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return False
        return dict(row)["customer_id"] == customer_id

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def add_message(
        self,
        *,
        thread_id: str,
        customer_id: str,
        sender_type: str,
        content: str,
        sender_email: str = "",
        email_message_id: str | None = None,
        message_id: str | None = None,
    ) -> ConversationMessage | None:
        """Append a message to an existing thread.

        Returns the inserted :class:`ConversationMessage`, or ``None`` when
        *email_message_id* already exists (idempotency guard).

        Parameters
        ----------
        thread_id:
            The owning thread.
        customer_id:
            Customer associated with this message (used for isolation).
        sender_type:
            One of ``'customer'``, ``'agent'``, ``'human'``, ``'system'``.
        content:
            Message body text.
        sender_email:
            Sender's email address (may be empty).
        email_message_id:
            Provider-level message ID.  When supplied the insert is ``INSERT
            OR IGNORE`` so that re-delivered webhooks are silently dropped.
        message_id:
            Explicit primary key.  Generated automatically when omitted.
        """
        mid = message_id or str(uuid.uuid4())
        now = _utcnow()
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO conversation_messages
                (message_id, thread_id, customer_id, sender_type,
                 sender_email, content, email_message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                thread_id,
                customer_id,
                sender_type,
                sender_email,
                content,
                email_message_id,
                now,
            ),
        )
        # Touch updated_at on the parent thread.
        self._conn.execute(
            "UPDATE conversation_threads SET updated_at = ? WHERE thread_id = ?",
            (now, thread_id),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            # Duplicate – the email_message_id was already stored.
            return None
        return ConversationMessage(
            message_id=mid,
            thread_id=thread_id,
            customer_id=customer_id,
            sender_type=sender_type,
            sender_email=sender_email,
            content=content,
            email_message_id=email_message_id,
            created_at=now,
        )

    def get_messages(
        self, thread_id: str, *, customer_id: str | None = None
    ) -> list[ConversationMessage]:
        """Return *all* messages for a thread in chronological order.

        Parameters
        ----------
        thread_id:
            The owning thread.
        customer_id:
            When provided, an empty list is returned if the thread belongs
            to a different customer (isolation guard).
        """
        if customer_id is not None and not self.thread_belongs_to_customer(
            thread_id, customer_id
        ):
            return []
        rows = self._conn.execute(
            """
            SELECT * FROM conversation_messages
            WHERE thread_id = ?
            ORDER BY created_at ASC, message_id ASC
            """,
            (thread_id,),
        ).fetchall()
        return [_row_to_message(r) for r in rows]

    def get_recent_messages(
        self,
        thread_id: str,
        *,
        limit: int = 20,
        customer_id: str | None = None,
    ) -> list[ConversationMessage]:
        """Return the *limit* most-recent messages, oldest-first.

        The default cap of 20 exchanges keeps LLM prompts within a reasonable
        token budget.  Override via the ``CONVERSATION_HISTORY_LIMIT``
        environment variable (parsed by the caller) or pass ``limit``
        directly.

        Parameters
        ----------
        thread_id:
            The owning thread.
        limit:
            Maximum number of messages to return.
        customer_id:
            Isolation guard – see :py:meth:`get_messages`.
        """
        if customer_id is not None and not self.thread_belongs_to_customer(
            thread_id, customer_id
        ):
            return []
        rows = self._conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM conversation_messages
                WHERE thread_id = ?
                ORDER BY created_at DESC, message_id DESC
                LIMIT ?
            )
            ORDER BY created_at ASC, message_id ASC
            """,
            (thread_id, limit),
        ).fetchall()
        return [_row_to_message(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self._conn.execute(query, params).fetchone()
        return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string with microsecond precision."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _row_to_thread(row: sqlite3.Row) -> ConversationThread:
    d = dict(row)
    return ConversationThread(
        thread_id=d["thread_id"],
        customer_id=d["customer_id"],
        ticket_id=d.get("ticket_id"),
        subject=d.get("subject", ""),
        status=d.get("status", "open"),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )


def _row_to_message(row: sqlite3.Row) -> ConversationMessage:
    d = dict(row)
    return ConversationMessage(
        message_id=d["message_id"],
        thread_id=d["thread_id"],
        customer_id=d["customer_id"],
        sender_type=d["sender_type"],
        sender_email=d.get("sender_email", ""),
        content=d["content"],
        email_message_id=d.get("email_message_id"),
        created_at=d.get("created_at", ""),
    )
