"""Test path configuration for the root-level database package.

Also provides shared fixtures for the Day 7-9 suites. They are deliberately
prefixed with ``sa_`` so they never collide with the per-file ``test_settings`` /
``db_engine`` / ``db_session`` / ``client`` fixtures that earlier days define
locally.
"""

import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (PROJECT_ROOT, SRC_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

loaded_db = sys.modules.get("db")
if loaded_db is not None and not str(getattr(loaded_db, "__file__", "")).startswith(
    str(PROJECT_ROOT)
):
    del sys.modules["db"]

DAYS_SECRET = "test-secret-key-that-is-long-enough-for-days-7-9"


@pytest.fixture(scope="session")
def sa_settings():
    """Settings bound to an in-memory database; no external services."""

    from core.config import Settings

    return Settings(
        jwt_secret_key=DAYS_SECRET,
        jwt_algorithm="HS256",
        access_token_expire_minutes=30,
        database_url="sqlite:///:memory:",
    )


@pytest.fixture(scope="session")
def sa_engine(sa_settings):
    """Session-scoped in-memory engine holding the full Day 1-9 schema."""

    engine = create_engine(
        sa_settings.database_url, connect_args={"check_same_thread": False}
    )
    from db.models import Base

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def sa_session(sa_engine) -> Generator[Session, None, None]:
    """Isolated session rolled back after each test."""

    connection = sa_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection)
    session = factory()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def sa_client(sa_session: Session, sa_settings) -> Generator[TestClient, None, None]:
    """TestClient wired to the isolated session and settings."""

    from api.main import app
    from core.config import get_settings
    from db.session import get_db

    get_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: sa_session
    app.dependency_overrides[get_settings] = lambda: sa_settings
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Day 10: authentication helpers for the legacy `/api/v1/*` routes
# ---------------------------------------------------------------------------


def _transient_user(
    *, role: str, tenant_id: str | None = None, customer_id: str | None = None
):
    """Build an unsaved ``User`` for dependency-override based tests.

    These routes are exercised against the legacy SQLite helpdesk database,
    which has no SQLAlchemy ``users`` table, so the identity is injected rather
    than looked up. Authorization still runs: ``require_permission`` reads the
    role from this object exactly as it would from a database row.
    """

    from db.models import User

    return User(
        id=f"test-{role.lower()}",
        tenant_id=tenant_id,
        customer_id=customer_id,
        email=f"{role.lower()}@example.com",
        password_hash="!",
        role=role,
        is_active=True,
    )


@pytest.fixture()
def auth_user():
    """The identity injected for authenticated legacy-route tests."""

    return _transient_user(role="SUPPORT_AGENT", tenant_id="tenant-legacy")


@pytest.fixture()
def legacy_client(auth_user) -> Generator[TestClient, None, None]:
    """A TestClient where a bearer token resolves to ``auth_user``."""

    from api.dependencies import get_current_user
    from api.main import app

    app.dependency_overrides[get_current_user] = lambda: auth_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Authorization header for :func:`legacy_client`."""

    return {"Authorization": "Bearer test-token"}
