"""Tests for the support-desk dashboard list endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_current_user
from api.main import app
from core.config import get_settings
from core.security import create_access_token
from db.models import User

TEST_SECRET = "test-secret-key-that-is-long-enough"


@pytest.fixture(autouse=True)
def override_deps():
    dummy_user = User(
        id="test-dashboard-user",
        email="dash@test.com",
        password_hash="hash",
        role="SUPPORT_AGENT",
        tenant_id="t1",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: dummy_user
    yield
    app.dependency_overrides.clear()


def _auth_header() -> dict[str, str]:
    settings = get_settings()
    token = create_access_token(
        user_id="test-dashboard-user",
        tenant_id="t1",
        role="SUPPORT_AGENT",
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_serves_html() -> None:
    with TestClient(app) as client:
        response = client.get("/dashboard")
    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()


def test_list_tickets_returns_tickets_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/tickets", headers=_auth_header())
    assert response.status_code == 200
    data = response.json()
    assert "tickets" in data
    assert isinstance(data["tickets"], list)


def test_list_jobs_returns_jobs_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/jobs", headers=_auth_header())
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert isinstance(data["jobs"], list)


def test_list_customers_returns_customers_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/customers", headers=_auth_header())
    assert response.status_code == 200
    data = response.json()
    assert "customers" in data
    assert isinstance(data["customers"], list)


def test_list_email_drafts_returns_drafts_key() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/support/email-drafts", headers=_auth_header())
    assert response.status_code == 200
    data = response.json()
    assert "drafts" in data
    assert isinstance(data["drafts"], list)
