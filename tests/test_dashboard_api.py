"""Tests for the support-desk dashboard list endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app


def test_dashboard_serves_html() -> None:
    with TestClient(app) as client:
        response = client.get("/dashboard")
    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()


def test_list_tickets_returns_tickets_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/tickets")
    assert response.status_code == 200
    data = response.json()
    assert "tickets" in data
    assert isinstance(data["tickets"], list)


def test_list_jobs_returns_jobs_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert isinstance(data["jobs"], list)


def test_list_customers_returns_customers_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/customers")
    assert response.status_code == 200
    data = response.json()
    assert "customers" in data
    assert isinstance(data["customers"], list)


def test_list_email_drafts_returns_drafts_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/support/email-drafts")
    assert response.status_code == 200
    data = response.json()
    assert "drafts" in data
    assert isinstance(data["drafts"], list)
