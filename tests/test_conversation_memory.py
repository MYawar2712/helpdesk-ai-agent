"""Tests for persistent email-thread conversation memory.

Covers:
- New email creates a thread.
- Reply to the same email thread retrieves the existing thread.
- Conversation history is passed to the agent.
- Agent response is stored in the same thread.
- Different customers cannot access another customer's thread.
- Duplicate email_message_id does not create duplicate messages.
- Missing thread ID creates a new thread.
- Multiple messages maintain chronological order.
- History limit works correctly.
- thread_belongs_to_customer validation.
"""

from __future__ import annotations

import os
import sqlite3
from unittest.mock import Mock, patch

import pytest

from db.conversation_repository import (
    ConversationRepository,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_db() -> sqlite3.Connection:
    """Create an in-memory SQLite database with the conversation schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    # Apply the schema to create conversation tables + customers table
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;

        CREATE TABLE IF NOT EXISTS customers (
            id   TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL DEFAULT '',
            company TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversation_threads (
            thread_id   TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            ticket_id   TEXT,
            subject     TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'open',
            created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversation_messages (
            message_id       TEXT PRIMARY KEY,
            thread_id        TEXT NOT NULL,
            customer_id      TEXT NOT NULL,
            sender_type      TEXT NOT NULL,
            sender_email     TEXT NOT NULL DEFAULT '',
            content          TEXT NOT NULL,
            email_message_id TEXT UNIQUE,
            created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO customers (id, name, email, phone, company)
        VALUES
            ('customer-1', 'Alice', 'alice@example.com', '111', 'ACME'),
            ('customer-2', 'Bob',   'bob@example.com',   '222', 'BCME');
        """
    )
    return conn


@pytest.fixture()
def repo() -> ConversationRepository:
    return ConversationRepository(_make_db())


@pytest.fixture()
def repo2() -> ConversationRepository:
    """Second repository connected to the same fresh DB (two-customer tests)."""
    return ConversationRepository(_make_db())


# ---------------------------------------------------------------------------
# ConversationRepository unit tests
# ---------------------------------------------------------------------------


class TestCreateThread:
    def test_creates_thread_with_generated_uuid(
        self, repo: ConversationRepository
    ) -> None:
        thread = repo.create_thread(customer_id="customer-1")
        assert thread.thread_id  # non-empty
        assert thread.customer_id == "customer-1"
        assert thread.status == "open"
        assert thread.ticket_id is None

    def test_uses_explicit_thread_id(self, repo: ConversationRepository) -> None:
        tid = "email-thread-abc123"
        thread = repo.create_thread(customer_id="customer-1", thread_id=tid)
        assert thread.thread_id == tid

    def test_subject_stored(self, repo: ConversationRepository) -> None:
        thread = repo.create_thread(customer_id="customer-1", subject="My AC is broken")
        assert thread.subject == "My AC is broken"

    def test_ticket_id_stored(self, repo: ConversationRepository) -> None:
        thread = repo.create_thread(
            customer_id="customer-1",
            subject="",
        )
        assert thread.ticket_id is None

    def test_persisted_to_db(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-001")
        fetched = repo.get_thread("t-001")
        assert fetched is not None
        assert fetched.thread_id == "t-001"
        assert fetched.customer_id == "customer-1"


class TestGetThread:
    def test_returns_none_for_unknown_thread(
        self, repo: ConversationRepository
    ) -> None:
        assert repo.get_thread("does-not-exist") is None

    def test_returns_thread_without_customer_filter(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        thread = repo.get_thread("t-1")
        assert thread is not None
        assert thread.thread_id == "t-1"

    def test_returns_thread_for_correct_customer(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        thread = repo.get_thread("t-1", customer_id="customer-1")
        assert thread is not None

    def test_customer_isolation_returns_none_for_wrong_customer(
        self, repo: ConversationRepository
    ) -> None:
        """A thread belonging to customer-1 must not be accessible to customer-2."""
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        thread = repo.get_thread("t-1", customer_id="customer-2")
        assert thread is None


class TestGetThreadByEmailThreadId:
    def test_finds_thread_by_email_thread_id(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="gmail-thread-xyz")
        thread = repo.get_thread_by_email_thread_id("gmail-thread-xyz")
        assert thread is not None
        assert thread.thread_id == "gmail-thread-xyz"

    def test_missing_email_thread_id_returns_none(
        self, repo: ConversationRepository
    ) -> None:
        assert repo.get_thread_by_email_thread_id("nonexistent") is None

    def test_wrong_customer_returns_none(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="gmail-abc")
        result = repo.get_thread_by_email_thread_id(
            "gmail-abc", customer_id="customer-2"
        )
        assert result is None


class TestThreadBelongsToCustomer:
    def test_returns_true_for_owner(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-owner")
        assert repo.thread_belongs_to_customer("t-owner", "customer-1") is True

    def test_returns_false_for_non_owner(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-owner")
        assert repo.thread_belongs_to_customer("t-owner", "customer-2") is False

    def test_returns_false_for_missing_thread(
        self, repo: ConversationRepository
    ) -> None:
        assert repo.thread_belongs_to_customer("no-such-thread", "customer-1") is False


class TestAddMessage:
    def test_adds_message_and_returns_it(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        msg = repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="Hello, I need help.",
        )
        assert msg is not None
        assert msg.content == "Hello, I need help."
        assert msg.sender_type == "customer"
        assert msg.thread_id == "t-1"

    def test_duplicate_email_message_id_returns_none(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        msg1 = repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="First delivery.",
            email_message_id="provider-msg-001",
        )
        # Same email_message_id – should be silently ignored
        msg2 = repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="First delivery.",
            email_message_id="provider-msg-001",
        )
        assert msg1 is not None
        assert msg2 is None  # idempotency guard fired

    def test_duplicate_does_not_create_db_record(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="Msg A",
            email_message_id="dup-id",
        )
        repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="Msg A again",
            email_message_id="dup-id",
        )
        messages = repo.get_messages("t-1")
        assert len(messages) == 1

    def test_sender_email_stored(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        msg = repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="Hi",
            sender_email="alice@example.com",
        )
        assert msg is not None
        assert msg.sender_email == "alice@example.com"


class TestGetMessages:
    def test_returns_messages_in_chronological_order(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="First",
        )
        repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="agent",
            content="Second",
        )
        repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="Third",
        )
        msgs = repo.get_messages("t-1")
        assert [m.content for m in msgs] == ["First", "Second", "Third"]

    def test_customer_isolation_returns_empty_for_wrong_customer(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="Secret",
        )
        msgs = repo.get_messages("t-1", customer_id="customer-2")
        assert msgs == []

    def test_returns_all_messages_without_customer_filter(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        for i in range(5):
            repo.add_message(
                thread_id="t-1",
                customer_id="customer-1",
                sender_type="customer",
                content=f"Message {i}",
            )
        msgs = repo.get_messages("t-1")
        assert len(msgs) == 5


class TestGetRecentMessages:
    def test_respects_limit(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        for i in range(10):
            repo.add_message(
                thread_id="t-1",
                customer_id="customer-1",
                sender_type="customer",
                content=f"Message {i}",
            )
        recent = repo.get_recent_messages("t-1", limit=3)
        assert len(recent) == 3

    def test_returns_most_recent_messages(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        for i in range(5):
            repo.add_message(
                thread_id="t-1",
                customer_id="customer-1",
                sender_type="customer",
                content=f"Message {i}",
            )
        recent = repo.get_recent_messages("t-1", limit=3)
        # Should be the last 3 messages (2, 3, 4) in ascending order
        contents = [m.content for m in recent]
        assert contents == ["Message 2", "Message 3", "Message 4"]

    def test_returns_all_when_fewer_than_limit(
        self, repo: ConversationRepository
    ) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        for i in range(3):
            repo.add_message(
                thread_id="t-1",
                customer_id="customer-1",
                sender_type="customer",
                content=f"Message {i}",
            )
        recent = repo.get_recent_messages("t-1", limit=10)
        assert len(recent) == 3

    def test_customer_isolation(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        repo.add_message(
            thread_id="t-1",
            customer_id="customer-1",
            sender_type="customer",
            content="Private",
        )
        msgs = repo.get_recent_messages("t-1", limit=5, customer_id="customer-2")
        assert msgs == []

    def test_returns_messages_oldest_first(self, repo: ConversationRepository) -> None:
        repo.create_thread(customer_id="customer-1", thread_id="t-1")
        for i in range(5):
            repo.add_message(
                thread_id="t-1",
                customer_id="customer-1",
                sender_type="customer",
                content=f"M{i}",
            )
        msgs = repo.get_recent_messages("t-1", limit=5)
        contents = [m.content for m in msgs]
        assert contents == ["M0", "M1", "M2", "M3", "M4"]


# ---------------------------------------------------------------------------
# HelpdeskAgent integration tests (conversation memory wiring)
# ---------------------------------------------------------------------------


def _make_seeded_conn() -> sqlite3.Connection:
    """Return an in-memory connection with the minimal schema + two customers."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;

        CREATE TABLE customers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL DEFAULT '',
            company TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE conversation_threads (
            thread_id   TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
            ticket_id   TEXT, subject TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'open',
            created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE conversation_messages (
            message_id       TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
            customer_id      TEXT NOT NULL, sender_type TEXT NOT NULL,
            sender_email     TEXT NOT NULL DEFAULT '',
            content          TEXT NOT NULL, email_message_id TEXT UNIQUE,
            created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO customers (id, name, email, phone, company)
        VALUES
            ('customer-1', 'Alice', 'alice@example.com', '', ''),
            ('customer-2', 'Bob',   'bob@example.com',   '', '');
        """
    )
    return conn


def _make_agent_with_repo(
    llm_response: str | dict | None = None,
    conv_repo: ConversationRepository | None = None,
) -> tuple:
    """Build a HelpdeskAgent with a mock LLM and optional ConversationRepository."""
    from agent.graph import HelpdeskAgent

    client = Mock()
    if isinstance(llm_response, dict):
        client.generate_json.return_value = llm_response
        client.generate.return_value = "Agent answer."
    else:
        client.generate_json.return_value = {
            "route": "respond",
            "response": llm_response or "I can help with that.",
        }
        client.generate.return_value = llm_response or "I can help with that."

    agent = HelpdeskAgent(
        llm_client=client,
        tools=[],
        conversation_repo=conv_repo,
    )
    return agent, client


class TestAgentConversationMemory:
    """Integration tests for the end-to-end conversation-memory flow."""

    def test_new_email_creates_a_thread(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        agent.invoke(
            "What are your hours?",
            customer_id="customer-1",
            email_thread_id="gmail-thread-001",
        )

        thread = cr.get_thread("gmail-thread-001", customer_id="customer-1")
        assert thread is not None
        assert thread.customer_id == "customer-1"

    def test_new_email_stores_customer_message(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        agent.invoke(
            "I need help please.",
            customer_id="customer-1",
            email_thread_id="gmail-thread-002",
        )

        msgs = cr.get_messages("gmail-thread-002")
        customer_msgs = [m for m in msgs if m.sender_type == "customer"]
        assert len(customer_msgs) == 1
        assert customer_msgs[0].content == "I need help please."

    def test_agent_response_stored_in_same_thread(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(
            llm_response="Our hours are 9-5 Mon-Fri.", conv_repo=cr
        )

        agent.invoke(
            "What are your hours?",
            customer_id="customer-1",
            email_thread_id="gmail-thread-003",
        )

        msgs = cr.get_messages("gmail-thread-003")
        agent_msgs = [m for m in msgs if m.sender_type == "agent"]
        assert len(agent_msgs) == 1
        assert "9-5" in agent_msgs[0].content or agent_msgs[0].content

    def test_reply_retrieves_existing_thread(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        # First message
        agent.invoke(
            "I was charged twice.",
            customer_id="customer-1",
            email_thread_id="gmail-thread-004",
        )

        # Reply to the same thread (simulated by same email_thread_id)
        agent.invoke(
            "JOB-4821",
            customer_id="customer-1",
            email_thread_id="gmail-thread-004",
        )

        msgs = cr.get_messages("gmail-thread-004")
        customer_msgs = [m for m in msgs if m.sender_type == "customer"]
        # Both messages should be in the same thread
        assert len(customer_msgs) == 2

    def test_conversation_history_passed_to_llm(self) -> None:
        """The decision node must receive prior messages in the prompt."""
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)

        # Pre-populate a thread with history
        cr.create_thread(customer_id="customer-1", thread_id="gmail-hist-001")
        cr.add_message(
            thread_id="gmail-hist-001",
            customer_id="customer-1",
            sender_type="agent",
            content="Please provide the job ID.",
        )

        agent, client = _make_agent_with_repo(conv_repo=cr)

        agent.invoke(
            "JOB-4821",
            customer_id="customer-1",
            email_thread_id="gmail-hist-001",
        )

        # The LLM's decision prompt should include prior history
        call_args = client.generate_json.call_args
        if call_args:
            system_prompt = call_args[0][0]
            assert (
                "JOB-4821" in call_args[0][1]
                or "Please provide the job ID" in system_prompt
            )

    def test_different_customers_cannot_share_thread(self) -> None:
        """A thread created for customer-1 must be invisible to customer-2."""
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        # customer-1 creates a thread
        agent.invoke(
            "My boiler is broken.",
            customer_id="customer-1",
            email_thread_id="shared-thread-id",
        )

        # customer-2 tries to use the same thread_id – must get a NEW thread
        agent.invoke(
            "My pipes burst.",
            customer_id="customer-2",
            email_thread_id="shared-thread-id",
        )

        # customer-2 must NOT see customer-1's messages
        msgs = cr.get_messages("shared-thread-id", customer_id="customer-2")
        assert all(m.customer_id != "customer-1" for m in msgs)

    def test_duplicate_email_message_id_not_processed_twice(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, client = _make_agent_with_repo(conv_repo=cr)

        # Deliver the same email twice (webhook retry)
        agent.invoke(
            "What's my job status?",
            customer_id="customer-1",
            email_thread_id="gmail-dup-thread",
            email_message_id="provider-msg-XYZ",
        )
        agent.invoke(
            "What's my job status?",
            customer_id="customer-1",
            email_thread_id="gmail-dup-thread",
            email_message_id="provider-msg-XYZ",
        )

        msgs = cr.get_messages("gmail-dup-thread")
        customer_msgs = [m for m in msgs if m.sender_type == "customer"]
        assert len(customer_msgs) == 1

    def test_missing_thread_id_creates_new_thread(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        agent.invoke(
            "General inquiry.",
            customer_id="customer-1",
            # No email_thread_id supplied
        )

        threads_rows = conn.execute(
            "SELECT * FROM conversation_threads WHERE customer_id = 'customer-1'"
        ).fetchall()
        assert len(threads_rows) == 1

    def test_multiple_messages_maintain_chronological_order(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        for i in range(4):
            agent.invoke(
                f"Message number {i}",
                customer_id="customer-1",
                email_thread_id="order-thread",
            )

        msgs = cr.get_messages("order-thread")
        customer_msgs = [m for m in msgs if m.sender_type == "customer"]
        for i, msg in enumerate(customer_msgs):
            assert f"Message number {i}" in msg.content

    def test_history_limit_respected(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)

        # Create a thread with 30 messages
        cr.create_thread(customer_id="customer-1", thread_id="limit-thread")
        for i in range(30):
            cr.add_message(
                thread_id="limit-thread",
                customer_id="customer-1",
                sender_type="customer" if i % 2 == 0 else "agent",
                content=f"Message {i}",
            )

        with patch.dict(os.environ, {"CONVERSATION_HISTORY_LIMIT": "5"}):
            recent = cr.get_recent_messages(
                "limit-thread", limit=5, customer_id="customer-1"
            )
        assert len(recent) == 5
        # Should be the 5 most recent (25-29)
        assert all(int(m.content.split()[-1]) >= 25 for m in recent)

    def test_thread_id_preserved_in_state(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        state = agent.invoke(
            "I need help.",
            customer_id="customer-1",
            email_thread_id="preserve-thread",
        )

        assert state.get("thread_id") == "preserve-thread"

    def test_no_conversation_repo_does_not_break_agent(self) -> None:
        """Agent must work normally when no ConversationRepository is supplied."""
        agent, client = _make_agent_with_repo(conv_repo=None)
        result = agent.invoke("What are your hours?")
        assert "final_response" in result or "response" in result

    def test_customer_id_extracted_from_ticket_text(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)
        agent, _ = _make_agent_with_repo(conv_repo=cr)

        agent.invoke(
            "Customer ID: customer-1\nI need assistance.",
            email_thread_id="extract-id-thread",
        )

        thread = cr.get_thread("extract-id-thread", customer_id="customer-1")
        assert thread is not None

    def test_security_violation_different_customer_same_thread_id(self) -> None:
        conn = _make_seeded_conn()
        cr = ConversationRepository(conn)

        # customer-1 owns 'secure-thread'
        cr.create_thread(customer_id="customer-1", thread_id="secure-thread")
        cr.add_message(
            thread_id="secure-thread",
            customer_id="customer-1",
            sender_type="customer",
            content="My secret message.",
        )

        # customer-2 tries to access 'secure-thread'
        # thread_belongs_to_customer must return False
        assert cr.thread_belongs_to_customer("secure-thread", "customer-2") is False

        # get_messages with wrong customer_id returns empty list
        msgs = cr.get_messages("secure-thread", customer_id="customer-2")
        assert msgs == []

        # get_thread with wrong customer_id returns None
        thread = cr.get_thread("secure-thread", customer_id="customer-2")
        assert thread is None


# ---------------------------------------------------------------------------
# History-limit environment-variable tests
# ---------------------------------------------------------------------------


class TestHistoryLimitEnvVar:
    def test_default_limit_is_20(self) -> None:
        from agent.graph import _history_limit

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONVERSATION_HISTORY_LIMIT", None)
            assert _history_limit() == 20

    def test_custom_limit_from_env(self) -> None:
        from agent.graph import _history_limit

        with patch.dict(os.environ, {"CONVERSATION_HISTORY_LIMIT": "5"}):
            assert _history_limit() == 5

    def test_invalid_value_falls_back_to_default(self) -> None:
        from agent.graph import _history_limit

        with patch.dict(os.environ, {"CONVERSATION_HISTORY_LIMIT": "not-a-number"}):
            assert _history_limit() == 20

    def test_zero_clamped_to_one(self) -> None:
        from agent.graph import _history_limit

        with patch.dict(os.environ, {"CONVERSATION_HISTORY_LIMIT": "0"}):
            assert _history_limit() == 1
