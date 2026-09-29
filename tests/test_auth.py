"""Tests for Day 2: Authentication System.

Covers:
- Password hashing and verification (unit tests, no I/O).
- JWT creation and decoding (unit tests, no I/O).
- POST /auth/register: success, duplicate email, bad tenant, weak password.
- POST /auth/login: success token format, wrong password, unknown email, deactivated.
- GET  /auth/me: valid token, expired token, missing token.

All tests use an in-memory SQLite database and override FastAPI dependency injection
so no external services (PostgreSQL, Redis, etc.) are needed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.security import create_access_token, hash_password, verify_password
from db.models import Base, Tenant, User
from db.session import get_db

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_SECRET = "test-secret-key-that-is-long-enough"
TEST_ALGORITHM = "HS256"
TEST_TTL = 30  # minutes


@pytest.fixture(scope="module")
def test_settings() -> Settings:
    """Settings wired to the in-memory test database."""
    return Settings(
        jwt_secret_key=TEST_SECRET,
        jwt_algorithm=TEST_ALGORITHM,
        access_token_expire_minutes=TEST_TTL,
        database_url="sqlite:///:memory:",
    )


@pytest.fixture(scope="module")
def db_engine(test_settings: Settings):
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine(
        test_settings.database_url, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Session:
    """Fresh database session for each test; rolls back after the test."""
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
    """FastAPI test client with dependency overrides for DB and settings."""
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from api.main import app
    from core.config import get_settings

    # Clear the lru_cache so our test settings take effect.
    get_settings.cache_clear()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_token(
    user_id: str,
    tenant_id: str | None,
    role: str,
    settings: Settings,
    *,
    expire_in_seconds: int | None = None,
) -> str:
    """Build a JWT with a custom expiry for testing expired-token scenarios."""

    if expire_in_seconds is not None:
        exp = datetime.now(UTC) + timedelta(seconds=expire_in_seconds)
        payload = {"sub": user_id, "tenant_id": tenant_id, "role": role, "exp": exp}
        return jwt.encode(
            payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
    return create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Unit tests: password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_differs_from_plaintext(self) -> None:
        hashed = hash_password("supersecret123")
        assert hashed != "supersecret123"

    def test_verify_correct_password_returns_true(self) -> None:
        hashed = hash_password("mysecretpassword")
        assert verify_password("mysecretpassword", hashed) is True

    def test_verify_wrong_password_returns_false(self) -> None:
        hashed = hash_password("correctpassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_same_password_produces_different_hashes(self) -> None:
        """bcrypt includes a random salt so each hash is unique."""
        h1 = hash_password("password123!")
        h2 = hash_password("password123!")
        assert h1 != h2

    def test_both_hashes_still_verify(self) -> None:
        h1 = hash_password("shared")
        h2 = hash_password("shared")
        assert verify_password("shared", h1)
        assert verify_password("shared", h2)


# ---------------------------------------------------------------------------
# Unit tests: JWT
# ---------------------------------------------------------------------------


class TestJWT:
    def test_create_and_decode_round_trip(self, test_settings: Settings) -> None:
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-abc",
            role="admin",
            settings=test_settings,
        )
        from core.security import decode_access_token

        payload = decode_access_token(token, test_settings)
        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "tenant-abc"
        assert payload["role"] == "admin"

    def test_super_admin_has_no_tenant(self, test_settings: Settings) -> None:
        token = create_access_token(
            user_id="super-1",
            tenant_id=None,
            role="super_admin",
            settings=test_settings,
        )
        from core.security import decode_access_token

        payload = decode_access_token(token, test_settings)
        assert payload["tenant_id"] is None

    def test_wrong_secret_raises_401(self, test_settings: Settings) -> None:
        from fastapi import HTTPException

        from core.security import decode_access_token

        bad_settings = Settings(
            jwt_secret_key="wrong-secret-key-value",
            database_url="sqlite:///:memory:",
        )
        token = create_access_token(
            user_id="u1", tenant_id=None, role="user", settings=test_settings
        )
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token, bad_settings)
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self, test_settings: Settings) -> None:
        from fastapi import HTTPException

        from core.security import decode_access_token

        # Token expired 1 second in the past.
        token = _make_token("u1", None, "user", test_settings, expire_in_seconds=-1)
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token, test_settings)
        assert exc_info.value.status_code == 401

    def test_token_contains_exp_claim(self, test_settings: Settings) -> None:
        token = create_access_token(
            user_id="u1", tenant_id=None, role="user", settings=test_settings
        )
        payload = jwt.decode(
            token,
            test_settings.jwt_secret_key,
            algorithms=[test_settings.jwt_algorithm],
        )
        assert "exp" in payload
        # exp should be in the future
        assert payload["exp"] > time.time()


# ---------------------------------------------------------------------------
# Integration tests: POST /auth/register
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_success(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/register",
            json={"email": "alice@example.com", "password": "SecurePass1!"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "alice@example.com"
        assert body["role"].upper() == "USER"
        assert body["tenant_id"] is None
        assert body["is_active"] is True
        assert "id" in body
        # Password must NOT appear in the response.
        assert "password" not in body
        assert "password_hash" not in body

    def test_register_with_tenant(
        self, client: TestClient, db_session: Session
    ) -> None:
        # Create a tenant first.
        tenant = Tenant(name="Acme Corp", slug="acme-register")
        db_session.add(tenant)
        db_session.commit()

        resp = client.post(
            "/auth/register",
            json={
                "email": "bob@acme.com",
                "password": "Password123!",
                "tenant_id": tenant.id,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["tenant_id"] == tenant.id

    def test_register_duplicate_email_returns_409(self, client: TestClient) -> None:
        payload = {"email": "dup@example.com", "password": "SecurePass1!"}
        r1 = client.post("/auth/register", json=payload)
        assert r1.status_code == 201
        r2 = client.post("/auth/register", json=payload)
        assert r2.status_code == 409

    def test_register_invalid_tenant_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/register",
            json={
                "email": "nobody@ghost.com",
                "password": "Password123!",
                "tenant_id": "non-existent-tenant-id",
            },
        )
        assert resp.status_code == 404

    def test_register_inactive_tenant_returns_400(
        self, client: TestClient, db_session: Session
    ) -> None:
        tenant = Tenant(name="Inactive Co", slug="inactive-co", is_active=False)
        db_session.add(tenant)
        db_session.commit()

        resp = client.post(
            "/auth/register",
            json={
                "email": "staff@inactive.com",
                "password": "Password123!",
                "tenant_id": tenant.id,
            },
        )
        assert resp.status_code == 400

    def test_register_short_password_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert resp.status_code == 422

    def test_register_invalid_email_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "ValidPass1!"},
        )
        assert resp.status_code == 422

    def test_password_is_stored_as_hash(
        self, client: TestClient, db_session: Session
    ) -> None:
        plain = "PlainTextPass99!"
        resp = client.post(
            "/auth/register",
            json={"email": "hashcheck@example.com", "password": plain},
        )
        assert resp.status_code == 201
        user_id = resp.json()["id"]
        user = db_session.get(User, user_id)
        assert user is not None
        assert user.password_hash != plain
        assert verify_password(plain, user.password_hash)


# ---------------------------------------------------------------------------
# Integration tests: POST /auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    def _register(self, client: TestClient, email: str, password: str) -> None:
        r = client.post("/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201

    def test_login_success_returns_token(self, client: TestClient) -> None:
        email, password = "login_ok@example.com", "GoodPassword1!"
        self._register(client, email, password)
        resp = client.post("/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 10

    def test_login_wrong_password_returns_401(self, client: TestClient) -> None:
        email, password = "wrong_pw@example.com", "CorrectPass1!"
        self._register(client, email, password)
        resp = client.post(
            "/auth/login", json={"email": email, "password": "WrongPass99!"}
        )
        assert resp.status_code == 401

    def test_login_unknown_email_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/login",
            json={"email": "ghost@nowhere.com", "password": "SomePass1!"},
        )
        assert resp.status_code == 401

    def test_login_deactivated_user_returns_403(
        self, client: TestClient, db_session: Session
    ) -> None:
        email, password = "deactivated@example.com", "GoodPass1!"
        self._register(client, email, password)

        # Deactivate the user directly.
        from sqlalchemy import select

        stmt = select(User).where(User.email == email)
        user = db_session.scalar(stmt)
        user.is_active = False
        db_session.commit()

        resp = client.post("/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 403

    def test_login_token_payload_is_correct(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        email, password = "payload_check@example.com", "GoodPassword1!"
        r = client.post(
            "/auth/register",
            json={"email": email, "password": password, "role": "support_agent"},
        )
        assert r.status_code == 201
        user_id = r.json()["id"]

        resp = client.post("/auth/login", json={"email": email, "password": password})
        token = resp.json()["access_token"]
        payload = jwt.decode(
            token,
            test_settings.jwt_secret_key,
            algorithms=[test_settings.jwt_algorithm],
        )
        assert payload["sub"] == user_id
        assert payload["role"].upper() == "SUPPORT_AGENT"
        assert "exp" in payload


# ---------------------------------------------------------------------------
# Integration tests: GET /auth/me
# ---------------------------------------------------------------------------


class TestMe:
    def _register_and_login(
        self, client: TestClient, email: str, password: str = "StrongPass1!"
    ) -> str:
        client.post("/auth/register", json={"email": email, "password": password})
        resp = client.post("/auth/login", json={"email": email, "password": password})
        return resp.json()["access_token"]

    def test_me_returns_user_profile(self, client: TestClient) -> None:
        token = self._register_and_login(client, "me_ok@example.com")
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "me_ok@example.com"
        assert body["is_active"] is True
        assert "password" not in body
        assert "password_hash" not in body

    def test_me_without_token_returns_401_or_403(self, client: TestClient) -> None:
        resp = client.get("/auth/me")
        assert resp.status_code in (401, 403)

    def test_me_with_bad_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            "/auth/me", headers={"Authorization": "Bearer this.is.not.valid"}
        )
        assert resp.status_code == 401

    def test_me_with_expired_token_returns_401(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        token = self._register_and_login(client, "expired_me@example.com")
        # Decode to get user_id then craft an expired token.
        payload = jwt.decode(
            token,
            test_settings.jwt_secret_key,
            algorithms=[test_settings.jwt_algorithm],
        )
        expired_token = _make_token(
            payload["sub"],
            payload["tenant_id"],
            payload["role"],
            test_settings,
            expire_in_seconds=-5,
        )
        resp = client.get(
            "/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert resp.status_code == 401
