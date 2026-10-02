"""Tests for Day 5: Customer Chatbot and Conversation Threads.

Covers
------
* Create conversation
* Send message
* Retrieve conversations list
* Retrieve single conversation
* Multiple messages remain in one conversation
* New chat creates a new conversation
* conversation_id == LangGraph thread_id
* LangGraph receives correct thread_id (mocked)
* AI response is saved
* Customer message is saved
* Customer can access own conversation
* Customer cannot access another customer's conversation
* Cross-tenant access fails
* Unauthenticated requests fail
* Invalid conversation ID fails
* All Day 1–4 tests remain passing (ensured by not touching existing logic)
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings, get_settings
from core.security import create_access_token, hash_password
from db.models import Base, Conversation, Customer, Message, Tenant, User
from db.session import get_db

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

TEST_SECRET = "test-secret-key-that-is-long-enough-for-day5"
TEST_ALGORITHM = "HS256"


@pytest.fixture(scope="module")
def test_settings() -> Settings:
    return Settings(
        jwt_secret_key=TEST_SECRET,
        jwt_algorithm=TEST_ALGORITHM,
        access_token_expire_minutes=30,
        database_url="sqlite:///:memory:",
    )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_engine(test_settings: Settings):
    engine = create_engine(
        test_settings.database_url, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Generator[Session, None, None]:
    connection = db_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection)
    session = factory()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(
    db_session: Session, test_settings: Settings
) -> Generator[TestClient, None, None]:
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from api.main import app

    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: test_settings

    # Attach a mock agent so no real LLM is needed.
    mock_agent = _make_mock_agent()
    app.state.agent = mock_agent

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Helpers – mock agent
# ---------------------------------------------------------------------------


def _make_mock_agent(response_text: str = "How can I help you?") -> MagicMock:
    """Return a mock agent whose .invoke() returns a deterministic state."""
    agent = MagicMock()
    agent.invoke.return_value = {"final_response": response_text, "route": "respond"}
    return agent


# ---------------------------------------------------------------------------
# Helpers – seed data
# ---------------------------------------------------------------------------


def _make_tenant(db: Session, *, slug: str | None = None) -> Tenant:
    tenant = Tenant(name="Test Corp", slug=slug or f"test-{uuid.uuid4().hex[:6]}")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def _make_customer(
    db: Session, *, tenant: Tenant, email: str | None = None
) -> Customer:
    customer = Customer(
        tenant_id=tenant.id,
        name="Alice Customer",
        email=email or f"alice-{uuid.uuid4().hex[:6]}@example.com",
        phone="555-0100",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def _make_customer_user(
    db: Session,
    *,
    tenant: Tenant,
    customer: Customer,
    email: str | None = None,
) -> User:
    user = User(
        tenant_id=tenant.id,
        customer_id=customer.id,
        email=email or f"user-{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("password123"),
        role="CUSTOMER",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_admin_user(db: Session, *, tenant: Tenant) -> User:
    user = User(
        tenant_id=tenant.id,
        email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("password123"),
        role="TENANT_ADMIN",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user: User, settings: Settings) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests: Conversation creation
# ---------------------------------------------------------------------------


def test_create_conversation_success(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Customer can create a new conversation."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)

    resp = client.post(
        "/chat/conversations",
        json={"subject": "My first question"},
        headers=_auth_header(user, test_settings),
    )

    assert resp.status_code == status.HTTP_201_CREATED, resp.json()
    data = resp.json()
    assert "conversation_id" in data
    assert data["tenant_id"] == tenant.id
    assert data["customer_id"] == customer.id
    assert data["subject"] == "My first question"
    assert data["status"] == "open"


def test_create_conversation_derives_ids_from_jwt(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """tenant_id and customer_id come from the JWT, never from the body."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)

    resp = client.post(
        "/chat/conversations",
        json={"subject": ""},
        headers=_auth_header(user, test_settings),
    )

    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["tenant_id"] == tenant.id
    assert data["customer_id"] == customer.id


def test_create_conversation_unauthenticated(client: TestClient) -> None:
    """Unauthenticated request returns 403 (bearer missing → auto_error)."""
    resp = client.post("/chat/conversations", json={"subject": "test"})
    assert resp.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


# ---------------------------------------------------------------------------
# Tests: New chat creates new conversation
# ---------------------------------------------------------------------------


def test_new_chat_creates_new_conversation(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Each POST /chat/conversations produces a distinct conversation_id."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    r1 = client.post("/chat/conversations", json={"subject": "conv 1"}, headers=headers)
    r2 = client.post("/chat/conversations", json={"subject": "conv 2"}, headers=headers)

    assert r1.status_code == status.HTTP_201_CREATED
    assert r2.status_code == status.HTTP_201_CREATED
    assert r1.json()["conversation_id"] != r2.json()["conversation_id"]


# ---------------------------------------------------------------------------
# Tests: List conversations
# ---------------------------------------------------------------------------


def test_list_conversations(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """GET /chat/conversations returns the customer's conversations."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    # Create 2 conversations.
    client.post("/chat/conversations", json={"subject": "A"}, headers=headers)
    client.post("/chat/conversations", json={"subject": "B"}, headers=headers)

    resp = client.get("/chat/conversations", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 2


def test_list_conversations_unauthenticated(client: TestClient) -> None:
    """Unauthenticated GET /chat/conversations is rejected."""
    resp = client.get("/chat/conversations")
    assert resp.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


# ---------------------------------------------------------------------------
# Tests: Get single conversation
# ---------------------------------------------------------------------------


def test_get_conversation_success(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Customer can retrieve their own conversation with messages."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": "Test conv"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    resp = client.get(f"/chat/conversations/{conv_id}", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["conversation_id"] == conv_id
    assert "messages" in data


def test_get_conversation_invalid_id(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Invalid conversation_id returns 404."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    resp = client.get(f"/chat/conversations/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Tests: Send message
# ---------------------------------------------------------------------------


def test_send_message_success(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Customer can send a message and receive an AI response."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": "Help me"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    resp = client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "What is the status of my job?"},
        headers=headers,
    )

    assert resp.status_code == status.HTTP_201_CREATED, resp.json()
    data = resp.json()
    assert data["conversation_id"] == conv_id
    assert "message_id" in data
    assert data["sender"] == "AI"
    assert isinstance(data["content"], str)
    assert len(data["content"]) > 0


def test_customer_message_saved(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Customer message is persisted to the database."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": ""}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "Hello AI"},
        headers=headers,
    )

    msgs = list(
        db_session.query(Message)
        .filter(
            Message.conversation_id == conv_id,
            Message.sender_type == "CUSTOMER",
        )
        .all()
    )
    assert len(msgs) == 1
    assert msgs[0].content == "Hello AI"


def test_ai_response_saved(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """AI response is persisted to the database."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": ""}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "Hello"},
        headers=headers,
    )

    ai_msgs = list(
        db_session.query(Message)
        .filter(
            Message.conversation_id == conv_id,
            Message.sender_type == "AI",
        )
        .all()
    )
    assert len(ai_msgs) == 1
    assert len(ai_msgs[0].content) > 0


# ---------------------------------------------------------------------------
# Tests: Multiple messages in one conversation
# ---------------------------------------------------------------------------


def test_multiple_messages_same_conversation(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Multiple messages are correctly associated with the same conversation."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": "Multi-turn"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    # Send 3 customer messages in the same conversation.
    for i in range(3):
        r = client.post(
            f"/chat/conversations/{conv_id}/messages",
            json={"content": f"Message {i}"},
            headers=headers,
        )
        assert r.status_code == status.HTTP_201_CREATED
        assert r.json()["conversation_id"] == conv_id

    # Retrieve the conversation and count messages (3 customer + 3 AI = 6).
    detail_resp = client.get(f"/chat/conversations/{conv_id}", headers=headers)
    msgs = detail_resp.json()["messages"]
    assert len(msgs) == 6


# ---------------------------------------------------------------------------
# Tests: conversation_id == LangGraph thread_id
# ---------------------------------------------------------------------------


def test_conversation_id_equals_langgraph_thread_id(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """The conversation_id is passed to the agent as the email_thread_id (thread_id)."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    from api.main import app

    create_resp = client.post(
        "/chat/conversations", json={"subject": "thread_id test"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    # Capture what thread_id the agent received.
    captured_thread_ids: list[str] = []
    original_invoke = app.state.agent.invoke

    def capturing_invoke(text, **kwargs):
        captured_thread_ids.append(kwargs.get("email_thread_id", ""))
        return original_invoke(text, **kwargs)

    app.state.agent.invoke = capturing_invoke

    client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "ping"},
        headers=headers,
    )

    # Restore.
    app.state.agent.invoke = original_invoke

    assert len(captured_thread_ids) == 1
    assert (
        captured_thread_ids[0] == conv_id
    ), f"Expected thread_id={conv_id!r}, got {captured_thread_ids[0]!r}"


def test_langgraph_receives_correct_thread_id(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Verify the agent.invoke call receives the conversation_id as email_thread_id."""
    from api.main import app

    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": "check"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    # Replace with a tracking mock.
    call_kwargs: list[dict] = []
    original_invoke = app.state.agent.invoke

    def spy_invoke(text, **kwargs):
        call_kwargs.append(kwargs)
        return original_invoke(text, **kwargs)

    app.state.agent.invoke = spy_invoke

    client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "check thread"},
        headers=headers,
    )

    app.state.agent.invoke = original_invoke

    assert len(call_kwargs) == 1
    assert call_kwargs[0].get("email_thread_id") == conv_id


# ---------------------------------------------------------------------------
# Tests: Customer isolation
# ---------------------------------------------------------------------------


def test_customer_can_access_own_conversation(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """A customer can access their own conversation."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": "mine"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    resp = client.get(f"/chat/conversations/{conv_id}", headers=headers)
    assert resp.status_code == status.HTTP_200_OK


def test_customer_cannot_access_another_customers_conversation(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """A customer cannot access a conversation belonging to another customer."""
    tenant = _make_tenant(db_session)

    customer_a = _make_customer(db_session, tenant=tenant)
    user_a = _make_customer_user(db_session, tenant=tenant, customer=customer_a)

    customer_b = _make_customer(db_session, tenant=tenant)
    user_b = _make_customer_user(db_session, tenant=tenant, customer=customer_b)

    # customer_a creates a conversation.
    create_resp = client.post(
        "/chat/conversations",
        json={"subject": "a's conv"},
        headers=_auth_header(user_a, test_settings),
    )
    conv_id = create_resp.json()["conversation_id"]

    # customer_b tries to access it → should get 404 (existence not revealed).
    resp = client.get(
        f"/chat/conversations/{conv_id}",
        headers=_auth_header(user_b, test_settings),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_customer_cannot_send_to_another_customers_conversation(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """A customer cannot send messages to another customer's conversation."""
    tenant = _make_tenant(db_session)

    customer_a = _make_customer(db_session, tenant=tenant)
    user_a = _make_customer_user(db_session, tenant=tenant, customer=customer_a)

    customer_b = _make_customer(db_session, tenant=tenant)
    user_b = _make_customer_user(db_session, tenant=tenant, customer=customer_b)

    create_resp = client.post(
        "/chat/conversations",
        json={"subject": "a"},
        headers=_auth_header(user_a, test_settings),
    )
    conv_id = create_resp.json()["conversation_id"]

    resp = client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "hacking"},
        headers=_auth_header(user_b, test_settings),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Tests: Cross-tenant access
# ---------------------------------------------------------------------------


def test_cross_tenant_access_fails(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """A user from tenant B cannot access a conversation owned by tenant A."""
    tenant_a = _make_tenant(db_session)
    tenant_b = _make_tenant(db_session)

    customer_a = _make_customer(db_session, tenant=tenant_a)
    user_a = _make_customer_user(db_session, tenant=tenant_a, customer=customer_a)

    customer_b = _make_customer(db_session, tenant=tenant_b)
    user_b = _make_customer_user(db_session, tenant=tenant_b, customer=customer_b)

    # tenant A creates a conversation.
    create_resp = client.post(
        "/chat/conversations",
        json={"subject": "tenant a"},
        headers=_auth_header(user_a, test_settings),
    )
    conv_id = create_resp.json()["conversation_id"]

    # tenant B user tries to access it.
    resp = client.get(
        f"/chat/conversations/{conv_id}",
        headers=_auth_header(user_b, test_settings),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_cross_tenant_message_send_fails(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """A user from tenant B cannot send messages to tenant A's conversation."""
    tenant_a = _make_tenant(db_session)
    tenant_b = _make_tenant(db_session)

    customer_a = _make_customer(db_session, tenant=tenant_a)
    user_a = _make_customer_user(db_session, tenant=tenant_a, customer=customer_a)

    customer_b = _make_customer(db_session, tenant=tenant_b)
    user_b = _make_customer_user(db_session, tenant=tenant_b, customer=customer_b)

    create_resp = client.post(
        "/chat/conversations",
        json={"subject": "a"},
        headers=_auth_header(user_a, test_settings),
    )
    conv_id = create_resp.json()["conversation_id"]

    resp = client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "cross-tenant attack"},
        headers=_auth_header(user_b, test_settings),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Tests: Delete (soft close) conversation
# ---------------------------------------------------------------------------


def test_delete_conversation(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Deleting a conversation soft-closes it (status → closed)."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": "to close"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]

    del_resp = client.delete(f"/chat/conversations/{conv_id}", headers=headers)
    assert del_resp.status_code == status.HTTP_204_NO_CONTENT

    # Verify it is now closed in DB.
    conv = db_session.get(Conversation, conv_id)
    assert conv is not None
    assert conv.status == "closed"


def test_send_message_to_closed_conversation_fails(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    """Sending a message to a closed conversation returns 422."""
    tenant = _make_tenant(db_session)
    customer = _make_customer(db_session, tenant=tenant)
    user = _make_customer_user(db_session, tenant=tenant, customer=customer)
    headers = _auth_header(user, test_settings)

    create_resp = client.post(
        "/chat/conversations", json={"subject": "closed"}, headers=headers
    )
    conv_id = create_resp.json()["conversation_id"]
    client.delete(f"/chat/conversations/{conv_id}", headers=headers)

    resp = client.post(
        f"/chat/conversations/{conv_id}/messages",
        json={"content": "still trying"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
