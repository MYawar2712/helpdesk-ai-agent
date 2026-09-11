from fastapi.testclient import TestClient

from api.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["models_loaded"] is True


def test_classify_ticket_returns_routing_response() -> None:
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
    with TestClient(app) as client:
        response = client.get("/api/v1/tickets/ticket-1/context")
    assert response.status_code == 200
    assert response.json()["ticket"]["id"] == "ticket-1"


def test_ticket_context_returns_404_for_unknown_ticket() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/tickets/does-not-exist/context")
    assert response.status_code == 404
