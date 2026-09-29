"""Tests for Day 3: RBAC and Authorization System."""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from auth.dependencies import (
    verify_customer_access,
    verify_tenant_access,
)
from auth.rbac import (
    Permission,
    Role,
    get_role_permissions,
    has_permission,
    validate_agent_permission,
)
from core.config import Settings, get_settings
from core.security import create_access_token, hash_password
from db.models import Base, Tenant, User
from db.session import get_db

TEST_SECRET = "test-secret-key-that-is-long-enough"
TEST_ALGORITHM = "HS256"


@pytest.fixture(scope="module")
def test_settings() -> Settings:
    return Settings(
        jwt_secret_key=TEST_SECRET,
        jwt_algorithm=TEST_ALGORITHM,
        access_token_expire_minutes=30,
        database_url="sqlite:///:memory:",
    )


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
def db_session(db_engine) -> Session:
    connection = db_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection)
    session = session_factory()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session: Session, test_settings: Settings) -> TestClient:
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from api.main import app

    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _auth_header(user: User, test_settings: Settings) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        settings=test_settings,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit tests: Role -> Permission Mapping
# ---------------------------------------------------------------------------


class TestRolePermissionMapping:
    def test_platform_admin_has_all_permissions(self) -> None:
        perms = get_role_permissions(Role.PLATFORM_ADMIN.value)
        assert Permission.USER_DELETE.value in perms
        assert Permission.TENANT_UPDATE.value in perms
        assert Permission.AUDIT_LOG_READ.value in perms

    def test_tenant_admin_permissions(self) -> None:
        perms = get_role_permissions(Role.TENANT_ADMIN.value)
        assert Permission.USER_CREATE.value in perms
        assert Permission.JOB_CANCEL.value in perms
        assert Permission.AUDIT_LOG_READ.value in perms

    def test_support_agent_permissions(self) -> None:
        perms = get_role_permissions(Role.SUPPORT_AGENT.value)
        assert Permission.TICKET_READ.value in perms
        assert Permission.JOB_ASSIGN.value in perms
        assert Permission.USER_DELETE.value not in perms
        assert Permission.TENANT_UPDATE.value not in perms

    def test_customer_permissions(self) -> None:
        perms = get_role_permissions(Role.CUSTOMER.value)
        assert Permission.TICKET_CREATE.value in perms
        assert Permission.JOB_CANCEL.value in perms
        assert Permission.USER_CREATE.value not in perms
        assert Permission.ENGINEER_CREATE.value not in perms

    def test_has_permission_utility(self) -> None:
        assert (
            has_permission(Role.SUPPORT_AGENT.value, Permission.TICKET_READ.value)
            is True
        )
        assert (
            has_permission(Role.CUSTOMER.value, Permission.USER_DELETE.value) is False
        )


# ---------------------------------------------------------------------------
# Unit tests: AI Agent Permission Foundation
# ---------------------------------------------------------------------------


class TestAIAgentPermissions:
    def test_job_agent_permissions(self) -> None:
        assert validate_agent_permission("JOB_AGENT", Permission.JOB_READ.value) is True
        assert (
            validate_agent_permission("JOB_AGENT", Permission.JOB_CREATE.value) is True
        )
        assert (
            validate_agent_permission("JOB_AGENT", Permission.JOB_ASSIGN.value) is True
        )
        # Prohibited actions
        assert (
            validate_agent_permission("JOB_AGENT", Permission.USER_DELETE.value)
            is False
        )
        assert (
            validate_agent_permission("JOB_AGENT", Permission.TENANT_UPDATE.value)
            is False
        )
        assert (
            validate_agent_permission("JOB_AGENT", Permission.INVOICE_UPDATE.value)
            is False
        )

    def test_unknown_agent_has_no_permissions(self) -> None:
        assert (
            validate_agent_permission("UNKNOWN_AGENT", Permission.JOB_READ.value)
            is False
        )


# ---------------------------------------------------------------------------
# Unit tests: Tenant & Customer Isolation Helpers
# ---------------------------------------------------------------------------


class TestIsolationHelpers:
    def test_tenant_isolation_same_tenant_allowed(self) -> None:
        user = User(
            id="u1",
            tenant_id="t1",
            role="TENANT_ADMIN",
            email="u1@t1.com",
            password_hash="h",
        )
        verify_tenant_access(user, "t1")  # Should not raise

    def test_tenant_isolation_different_tenant_denied(self) -> None:
        user = User(
            id="u1",
            tenant_id="t1",
            role="TENANT_ADMIN",
            email="u1@t1.com",
            password_hash="h",
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            verify_tenant_access(user, "t2")
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    def test_platform_admin_bypasses_tenant_isolation(self) -> None:
        user = User(
            id="u1",
            tenant_id=None,
            role="PLATFORM_ADMIN",
            email="admin@platform.com",
            password_hash="h",
        )
        verify_tenant_access(user, "t2")  # Should not raise

    def test_customer_isolation(self) -> None:
        user = User(
            id="u1",
            tenant_id="t1",
            role="CUSTOMER",
            email="c1@t1.com",
            password_hash="h",
        )
        user.customer_id = "cust1"
        verify_customer_access(user, "cust1")  # Should not raise

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            verify_customer_access(user, "cust2")
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Integration tests: User Management & Privilege Escalation Prevention
# ---------------------------------------------------------------------------


class TestUserManagement:
    def test_tenant_admin_can_create_support_agent(
        self, client: TestClient, db_session: Session, test_settings: Settings
    ) -> None:
        tenant = Tenant(name="Acme", slug="acme-um1")
        db_session.add(tenant)
        db_session.commit()

        admin = User(
            email="admin@acme.com",
            password_hash=hash_password("Pass123!"),
            role="TENANT_ADMIN",
            tenant_id=tenant.id,
        )
        db_session.add(admin)
        db_session.commit()

        headers = _auth_header(admin, test_settings)
        resp = client.post(
            "/users",
            json={
                "email": "agent1@acme.com",
                "password": "AgentPassword1!",
                "role": "SUPPORT_AGENT",
            },
            headers=headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "agent1@acme.com"
        assert body["role"] == "SUPPORT_AGENT"
        assert body["tenant_id"] == tenant.id

    def test_tenant_admin_cannot_escalate_to_platform_admin(
        self, client: TestClient, db_session: Session, test_settings: Settings
    ) -> None:
        tenant = Tenant(name="Acme2", slug="acme-um2")
        db_session.add(tenant)
        db_session.commit()

        admin = User(
            email="admin2@acme.com",
            password_hash=hash_password("Pass123!"),
            role="TENANT_ADMIN",
            tenant_id=tenant.id,
        )
        db_session.add(admin)
        db_session.commit()

        headers = _auth_header(admin, test_settings)
        resp = client.post(
            "/users",
            json={
                "email": "superhacker@acme.com",
                "password": "AgentPassword1!",
                "role": "PLATFORM_ADMIN",
            },
            headers=headers,
        )
        assert resp.status_code == 403

    def test_self_registration_cannot_grant_privileged_role(
        self, client: TestClient, db_session: Session
    ) -> None:
        tenant = Tenant(name="Acme3", slug="acme-um3")
        db_session.add(tenant)
        db_session.commit()

        resp = client.post(
            "/auth/register",
            json={
                "email": "selfregister@acme.com",
                "password": "Password123!",
                "role": "TENANT_ADMIN",
                "tenant_id": tenant.id,
            },
        )
        assert resp.status_code == 201
        # Should be downgraded to CUSTOMER
        assert resp.json()["role"] == "CUSTOMER"

    def test_tenant_admin_cannot_access_other_tenant_users(
        self, client: TestClient, db_session: Session, test_settings: Settings
    ) -> None:
        t1 = Tenant(name="T1", slug="t1-um")
        t2 = Tenant(name="T2", slug="t2-um")
        db_session.add_all([t1, t2])
        db_session.commit()

        admin1 = User(
            email="admin1@t1.com",
            password_hash="h",
            role="TENANT_ADMIN",
            tenant_id=t1.id,
        )
        user2 = User(
            email="user2@t2.com",
            password_hash="h",
            role="SUPPORT_AGENT",
            tenant_id=t2.id,
        )
        db_session.add_all([admin1, user2])
        db_session.commit()

        headers = _auth_header(admin1, test_settings)
        resp = client.get(f"/users/{user2.id}", headers=headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Integration tests: Endpoint Protection & Permission Checks
# ---------------------------------------------------------------------------


class TestProtectedRoutes:
    def test_unauthenticated_request_returns_401_or_403(
        self, client: TestClient
    ) -> None:
        resp = client.get("/api/v1/tickets")
        assert resp.status_code in (401, 403)

    def test_user_with_permission_can_access_tickets(
        self, client: TestClient, db_session: Session, test_settings: Settings
    ) -> None:
        agent = User(
            email="agent@support.com",
            password_hash="h",
            role="SUPPORT_AGENT",
            tenant_id="t1",
        )
        db_session.add(agent)
        db_session.commit()

        headers = _auth_header(agent, test_settings)
        resp = client.get("/api/v1/tickets", headers=headers)
        assert resp.status_code == 200

    def test_user_without_permission_receives_403(
        self, client: TestClient, db_session: Session, test_settings: Settings
    ) -> None:
        cust = User(
            email="cust@client.com", password_hash="h", role="CUSTOMER", tenant_id="t1"
        )
        db_session.add(cust)
        db_session.commit()

        headers = _auth_header(cust, test_settings)
        resp = client.get("/users", headers=headers)
        assert resp.status_code == 403
