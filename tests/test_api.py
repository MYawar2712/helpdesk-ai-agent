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
