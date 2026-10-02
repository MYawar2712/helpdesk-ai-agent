"""Reusable factories for the Day 7-9 test suites.

Kept separate from ``conftest.py`` so the helper functions can be imported
explicitly by each test module, matching the project's flat ``tests/``
convention.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.security import create_access_token, hash_password
from db.models import (
    AIConfiguration,
    Base,
    Customer,
    KnowledgeDocument,
    Tenant,
    User,
)


def make_tenant(
    session: Session, *, name: str = "Acme", slug: str | None = None
) -> Tenant:
    tenant = Tenant(name=name, slug=slug or f"t-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def make_customer(
    session: Session, *, tenant: Tenant, email: str | None = None
) -> Customer:
    customer = Customer(
        tenant_id=tenant.id,
        name="Test Customer",
        email=email or f"c-{uuid.uuid4().hex[:8]}@example.com",
        phone="555-0100",
    )
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


def make_user(
    session: Session,
    *,
    tenant: Tenant,
    role: str = "TENANT_ADMIN",
    customer: Customer | None = None,
    is_active: bool = True,
) -> User:
    user = User(
        tenant_id=tenant.id,
        customer_id=customer.id if customer else None,
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("password123"),
        role=role,
        is_active=is_active,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def auth_header(user: User, settings: Settings) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


def make_ai_config(
    session: Session,
    *,
    tenant: Tenant,
    agent_type: str = "SUPPORT_AGENT",
    instructions: str | None = None,
    tone: str | None = None,
    business_rules: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    is_active: bool = True,
) -> AIConfiguration:
    row = AIConfiguration(
        tenant_id=tenant.id,
        agent_type=agent_type,
        instructions=instructions,
        tone=tone,
        business_rules=business_rules,
        allowed_tools=allowed_tools,
        is_active=is_active,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def make_knowledge_document(
    session: Session,
    *,
    tenant: Tenant,
    name: str,
    content: str,
    tmp_path: Path,
    status: str = "pending",
) -> KnowledgeDocument:
    """Create a document with real file content so processing can run."""

    filename = f"{uuid.uuid4().hex}.md"
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    document = KnowledgeDocument(
        tenant_id=tenant.id,
        name=name,
        file_path=str(path),
        processing_status=status,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def temp_sqlalchemy(tmp_path: Path, name: str = "sa.sqlite3") -> Session:
    """Create a throwaway file-backed session for persistence tests."""

    engine = create_engine(f"sqlite:///{(tmp_path / name).as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def legacy_helpdesk(
    tmp_path: Path | None = None, *, seed: bool = True
) -> tuple[Any, sqlite3.Connection]:
    """Build an isolated legacy helpdesk repository backed by SQLite.

    ``seed=False`` reuses an existing database, which is what a simulated
    application restart needs: business data must survive, not be re-seeded.
    """

    from clients.nosql_client import NoSQLClient
    from db.data_layer import HelpdeskDataRepository
    from db.seed import seed_database

    target = tmp_path or Path(".")
    database = target / "helpdesk_test.sqlite3"
    existed = database.exists()
    connection = sqlite3.connect(str(database), check_same_thread=False)
    if seed or not existed:
        seed_database(connection)
    nosql = NoSQLClient(sqlite3.connect(":memory:"))
    return HelpdeskDataRepository(connection, nosql), connection


def legacy_job_ids(connection: sqlite3.Connection, customer_id: str) -> dict[str, str]:
    """Return active and any job ids for a customer from the legacy store."""

    active = connection.execute(
        "SELECT id FROM jobs WHERE customer_id = ? "
        "AND status IN ('scheduled','pending') LIMIT 1",
        (customer_id,),
    ).fetchone()
    any_job = connection.execute(
        "SELECT id FROM jobs WHERE customer_id = ? LIMIT 1", (customer_id,)
    ).fetchone()
    return {
        "active": active[0] if active else "",
        "any": any_job[0] if any_job else "",
    }


def job_status(connection: sqlite3.Connection, job_id: str) -> str | None:
    row = connection.execute(
        "SELECT status FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return row[0] if row else None
