"""Unit tests for FastAPI endpoints including health, classification, and chat."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.main import app


def test_root_endpoint() -> None:
    """Test GET / returns root status information."""
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["message"] == "Helpdesk AI Agent API"
    assert "version" in data


def test_health_endpoint() -> None:
    """Test GET /health returns service readiness."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["models_loaded"] is True


def test_classify_ticket_returns_routing_response() -> None:
    """Test POST /api/v1/tickets/classify returns ML and routing decisions."""
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tickets/classify",
            json={
                "title": "Server outage",
                "description": "All sites are unavailable",
                "customer_id": "customer-1",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert {
        "predicted_category",
        "predicted_priority",
        "confidence_score",
    } <= body.keys()
    assert isinstance(body["reasons"], list)


def test_ticket_context_returns_seeded_ticket() -> None:
    """Test GET /api/v1/tickets/{id}/context returns seeded data."""
    with TestClient(app) as client:
        response = client.get("/api/v1/tickets/ticket-1/context")
    assert response.status_code == 200
    assert response.json()["ticket"]["id"] == "ticket-1"


def test_ticket_context_returns_404_for_unknown_ticket() -> None:
    """Test GET /api/v1/tickets/{id}/context returns 404 when ticket is missing."""
    with TestClient(app) as client:
        response = client.get("/api/v1/tickets/does-not-exist/context")
    assert response.status_code == 404


def test_chat_endpoint_successful_response() -> None:
    """Test POST /chat returns a valid response with mocked agent."""
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "route": "respond",
        "response": "AC repairs are covered for 2 years under warranty.",
        "final_response": "AC repairs are covered for 2 years under warranty.",
        "tool_name": "",
        "tool_result": {},
    }

    with TestClient(app) as client:
        app.state.agent = mock_agent
        response = client.post(
            "/chat",
            json={"message": "What is the warranty policy for AC repairs?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "AC repairs are covered for 2 years under warranty."
    assert data["route"] == "respond"
    assert data["tool_name"] is None
    assert data["tool_result"] is None
    assert isinstance(data["sources"], list)
    mock_agent.invoke.assert_called_once_with(
        "What is the warranty policy for AC repairs?"
    )


def test_chat_endpoint_missing_or_invalid_message() -> None:
    """Test POST /chat returns 422 for missing or empty message payload."""
    with TestClient(app) as client:
        # Missing message key
        response1 = client.post("/chat", json={})
        assert response1.status_code == 422

        # Empty string message
        response2 = client.post("/chat", json={"message": ""})
        assert response2.status_code == 422

        # Whitespace-only string message
        response3 = client.post("/chat", json={"message": "   "})
        assert response3.status_code == 422


def test_chat_endpoint_agent_failure() -> None:
    """Test POST /chat returns 500 when agent execution fails."""
    mock_agent = MagicMock()
    mock_agent.invoke.side_effect = RuntimeError("LLM connection timeout")

    with TestClient(app) as client:
        app.state.agent = mock_agent
        response = client.post(
            "/chat",
            json={"message": "Help with my boiler!"},
        )

    assert response.status_code == 500
    assert "detail" in response.json()


def test_customer_inquiry_creates_reviewable_ai_draft() -> None:
    """Customer inquiry drafts an AI reply but leaves it awaiting review."""
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "route": "respond",
        "response": "Thanks for reaching out. We can help with that.",
        "final_response": "Thanks for reaching out. We can help with that.",
        "tool_name": "",
        "tool_result": {},
    }

    with TestClient(app) as client:
        app.state.agent = mock_agent
        response = client.post(
            "/api/v1/customer-inquiries/draft-reply",
            json={
                "ticket_id": "ticket-1",
                "customer_id": "customer-1",
                "message": "Hi, can you help me understand your opening hours?",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["agent_response"] == "Thanks for reaching out. We can help with that."
    assert body["route"] == "respond"
    assert body["draft"]["status"] == "human_review"
    assert body["draft"]["original_ai_draft"] == body["agent_response"]
    mock_agent.invoke.assert_called_once_with(
        "Customer ID: customer-1\n"
        "Ticket ID: ticket-1\n"
        "Message: Hi, can you help me understand your opening hours?"
    )


def test_customer_inquiry_agent_failure_creates_reviewable_handoff_draft() -> None:
    """Agent failures become reviewable drafts instead of raw 500s."""
    mock_agent = MagicMock()
    mock_agent.invoke.side_effect = RuntimeError("LLM unavailable")

    with TestClient(app) as client:
        app.state.agent = mock_agent
        response = client.post(
            "/api/v1/customer-inquiries/draft-reply",
            json={
                "ticket_id": "ticket-1",
                "customer_id": "customer-1",
                "message": "can u tell me your business hours",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["route"] == "handoff"
    assert body["draft"]["status"] == "human_review"
    assert "human support" in body["agent_response"]


def test_customer_inquiry_without_ticket_id_creates_new_ticket() -> None:
    """When ticket_id is omitted, draft-reply creates a brand new ticket in SQLite."""
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "final_response": "Here is information on your inquiry.",
        "route": "respond",
    }

    with TestClient(app) as client:
        app.state.agent = mock_agent
        response = client.post(
            "/api/v1/customer-inquiries/draft-reply",
            json={
                "customer_id": "customer-1",
                "message": "I need help with my new subscription",
            },
        )

    assert response.status_code == 201
    body = response.json()
    new_ticket_id = body["draft"]["ticket_id"]
    assert new_ticket_id.startswith("ticket-")
    assert new_ticket_id != "ticket-1"
    assert body["agent_response"] == "Here is information on your inquiry."


def test_customer_inquiry_repair_request_creates_job_and_assigns_engineer() -> None:
    """Customer inquiry with scheduling intent creates job immediately and returns
    confirmation."""
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "final_response": "We can schedule an HVAC technician to repair your AC.",
        "route": "respond",
    }

    with TestClient(app) as client:
        app.state.agent = mock_agent
        response = client.post(
            "/api/v1/customer-inquiries/draft-reply",
            json={
                "customer_id": "customer-1",
                "message": (
                    "I want to make a job lock for my AC repair make it on "
                    "monday at 9 am"
                ),
            },
        )

        assert response.status_code == 201
        body = response.json()
        # Job is created immediately, not deferred to send
        assert body["route"] == "respond"
        assert body["tool_name"] == "schedule_job"
        assert (
            "scheduled" in body["agent_response"].lower()
            or "job id" in body["agent_response"].lower()
        )
        assert body["draft"]["status"] == "human_review"
        # Agent should NOT be invoked for scheduling requests
        mock_agent.invoke.assert_not_called()


def test_create_job_for_ticket_api_endpoint() -> None:
    """POST /api/v1/tickets/{ticket_id}/create-job creates job and assigns engineer."""
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tickets/ticket-1/create-job",
            json={
                "customer_id": "customer-1",
                "title": "Onsite Electrical Repair",
                "description": "Inspect main breaker box for ticket-1.",
                "required_skill": "electrical",
                "service_area": "New York",
                "priority": "high",
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert "ticket" in data
    assert "job" in data
    assert data["job"]["assigned_engineer_id"] is not None
    assert data["ticket"]["job_id"] == data["job"]["id"]
