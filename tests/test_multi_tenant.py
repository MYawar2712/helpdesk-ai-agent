"""Tests for Day 1: Multi-Tenant Database Architecture and Isolation Rules."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import (
    Base,
    User,
)
from services.tenant_data_service import CrossTenantAccessError, TenantDataService


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite database session for unit testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_model_creation_and_relationships(db_session: Session) -> None:
    """Verify all 12 multi-tenant ORM models can be instantiated with relationships."""
    service = TenantDataService(db_session)

    # 1. Tenant
    tenant = service.create_tenant(name="Acme Corp", slug="acme")
    assert tenant.id is not None
    assert tenant.slug == "acme"
    assert tenant.is_active is True

    # 2. User
    user = User(
        tenant_id=tenant.id,
        email="admin@acme.com",
        password_hash="hashed_secret",
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    assert user.id is not None
    assert user.tenant.name == "Acme Corp"

    # 3. Customer
    customer = service.create_customer(
        tenant_id=tenant.id,
        name="Alice Johnson",
        email="alice@example.com",
        phone="555-0199",
    )
    assert customer.id is not None
    assert customer.tenant_id == tenant.id

    # 4. Engineer
    engineer = service.create_engineer(
        tenant_id=tenant.id,
        name="Bob Technician",
        email="bob@acme.com",
        skills=["electrical", "plumbing"],
    )
    assert engineer.id is not None
    assert "electrical" in engineer.skills

    # 5. Job
    job = service.create_job(
        tenant_id=tenant.id,
        customer_id=customer.id,
        title="Repair AC Unit",
        description="AC compressor is noisy",
        assigned_engineer_id=engineer.id,
    )
    assert job.id is not None
    assert job.customer.name == "Alice Johnson"
    assert job.assigned_engineer.name == "Bob Technician"

    # 6. Ticket (with related job)
    ticket = service.create_ticket(
        tenant_id=tenant.id,
        customer_id=customer.id,
        title="AC Noise",
        description="AC compressor noise issue",
        related_job_id=job.id,
        intent="TECHNICAL_SUPPORT",
    )
    assert ticket.id is not None
    assert ticket.related_job.id == job.id

    # 7. Invoice
    invoice = service.create_invoice(
        tenant_id=tenant.id,
        customer_id=customer.id,
        job_id=job.id,
        amount=Decimal("150.00"),
        due_date=datetime.now(UTC),
    )
    assert invoice.id is not None
    assert invoice.amount == Decimal("150.00")

    # 8. Conversation
    conv = service.create_conversation(
        tenant_id=tenant.id,
        customer_id=customer.id,
        ticket_id=ticket.id,
        subject="AC Unit Noise Inquiry",
    )
    assert conv.id is not None
    assert conv.ticket.id == ticket.id

    # 9. Message
    msg = service.add_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Hello, when will the engineer arrive?",
    )
    assert msg.id is not None
    assert msg.conversation.id == conv.id

    # 10. AIConfiguration
    ai_cfg = service.set_ai_configuration(
        tenant_id=tenant.id,
        global_instructions="Be polite and clear.",
        tone="professional",
        escalation_rules={"urgent": True},
    )
    assert ai_cfg.id is not None
    assert ai_cfg.tone == "professional"

    # 11. KnowledgeDocument
    doc = service.create_knowledge_document(
        tenant_id=tenant.id,
        name="HVAC Manual",
        file_path="/docs/hvac_manual.pdf",
        doc_metadata={"category": "HVAC"},
    )
    assert doc.id is not None
    assert doc.name == "HVAC Manual"

    # 12. AuditLog
    log = service.create_audit_log(
        tenant_id=tenant.id,
        action="ticket_created",
        resource_type="ticket",
        resource_id=ticket.id,
        actor_user_id=user.id,
    )
    assert log.id is not None
    assert log.resource_id == ticket.id


def test_tenant_isolation_retrieval(db_session: Session) -> None:
    """Verify Tenant A cannot retrieve Tenant B's entities."""
    service = TenantDataService(db_session)

    t1 = service.create_tenant("Tenant A", "tenant-a")
    t2 = service.create_tenant("Tenant B", "tenant-b")

    cust_a = service.create_customer(t1.id, "Cust A", "a@t1.com", "111")
    cust_b = service.create_customer(t2.id, "Cust B", "b@t2.com", "222")

    job_a = service.create_job(t1.id, cust_a.id, "Job A", "Desc A")
    job_b = service.create_job(t2.id, cust_b.id, "Job B", "Desc B")

    tkt_a = service.create_ticket(
        t1.id, cust_a.id, "Tkt A", "Desc A", related_job_id=job_a.id
    )
    tkt_b = service.create_ticket(
        t2.id, cust_b.id, "Tkt B", "Desc B", related_job_id=job_b.id
    )

    inv_a = service.create_invoice(
        t1.id, cust_a.id, job_a.id, Decimal("100.00"), datetime.now(UTC)
    )
    inv_b = service.create_invoice(
        t2.id, cust_b.id, job_b.id, Decimal("200.00"), datetime.now(UTC)
    )

    conv_a = service.create_conversation(t1.id, cust_a.id, ticket_id=tkt_a.id)
    conv_b = service.create_conversation(t2.id, cust_b.id, ticket_id=tkt_b.id)

    # 1. Customer Isolation
    assert service.get_customer(t1.id, cust_a.id) is not None
    assert service.get_customer(t1.id, cust_b.id) is None
    assert cust_b not in service.list_customers(t1.id)

    # 2. Job Isolation
    assert service.get_job(t1.id, job_a.id) is not None
    assert service.get_job(t1.id, job_b.id) is None
    assert job_b not in service.list_jobs(t1.id)

    # 3. Ticket Isolation
    assert service.get_ticket(t1.id, tkt_a.id) is not None
    assert service.get_ticket(t1.id, tkt_b.id) is None
    assert tkt_b not in service.list_tickets(t1.id)

    # 4. Invoice Isolation
    assert service.get_invoice(t1.id, inv_a.id) is not None
    assert service.get_invoice(t1.id, inv_b.id) is None
    assert inv_b not in service.list_invoices(t1.id)

    # 5. Conversation Isolation
    assert service.get_conversation(t1.id, conv_a.id) is not None
    assert service.get_conversation(t1.id, conv_b.id) is None


def test_messages_cannot_be_accessed_across_tenants(db_session: Session) -> None:
    """Verify messages inside Tenant B's conversation cannot be accessed by Tenant A."""
    service = TenantDataService(db_session)

    t1 = service.create_tenant("Tenant 1", "t1")
    t2 = service.create_tenant("Tenant 2", "t2")

    _c1 = service.create_customer(t1.id, "Cust 1", "c1@t1.com", "111")
    c2 = service.create_customer(t2.id, "Cust 2", "c2@t2.com", "222")

    conv2 = service.create_conversation(t2.id, c2.id, subject="Secret Thread")
    _msg2 = service.add_message(t2.id, conv2.id, "customer", "Private tenant message")

    # Tenant A attempts to fetch messages for conv2
    messages_for_t1 = service.get_messages(tenant_id=t1.id, conversation_id=conv2.id)
    assert messages_for_t1 == []

    # Tenant A attempts to add a message to Tenant B's conversation
    with pytest.raises(CrossTenantAccessError):
        service.add_message(
            tenant_id=t1.id,
            conversation_id=conv2.id,
            sender_type="agent",
            content="Hacked",
        )


def test_cross_tenant_record_linking_prevented(db_session: Session) -> None:
    """Verify related records cannot be linked across different tenants."""
    service = TenantDataService(db_session)

    t1 = service.create_tenant("Tenant 1", "t1")
    t2 = service.create_tenant("Tenant 2", "t2")

    c1 = service.create_customer(t1.id, "Cust 1", "c1@t1.com", "111")
    c2 = service.create_customer(t2.id, "Cust 2", "c2@t2.com", "222")

    _j1 = service.create_job(t1.id, c1.id, "Job 1", "Desc 1")
    j2 = service.create_job(t2.id, c2.id, "Job 2", "Desc 2")

    # 1. Attempt to create Tenant A ticket referencing Tenant B customer
    with pytest.raises(CrossTenantAccessError):
        service.create_ticket(t1.id, c2.id, "Bad Ticket", "Desc")

    # 2. Attempt to create Tenant A ticket referencing Tenant B job
    with pytest.raises(CrossTenantAccessError):
        service.create_ticket(t1.id, c1.id, "Bad Ticket", "Desc", related_job_id=j2.id)

    # 3. Attempt to create Tenant A invoice referencing Tenant B job
    with pytest.raises(CrossTenantAccessError):
        service.create_invoice(t1.id, c1.id, j2.id, Decimal("50.00"), datetime.now(UTC))


def test_nullable_relationships_work(db_session: Session) -> None:
    """Verify nullable relationships (e.g. ticket without a job) work."""
    service = TenantDataService(db_session)

    t = service.create_tenant("Tenant Null", "null-test")
    c = service.create_customer(t.id, "Cust Null", "null@test.com", "000")

    # Ticket without job
    ticket = service.create_ticket(
        tenant_id=t.id,
        customer_id=c.id,
        title="Standalone Ticket",
        description="No job required",
        related_job_id=None,
    )
    assert ticket.id is not None
    assert ticket.related_job_id is None
    assert ticket.related_job is None

    # Super-admin User without tenant
    super_admin = User(
        tenant_id=None,
        email="superadmin@platform.com",
        password_hash="secret",
        role="superadmin",
    )
    db_session.add(super_admin)
    db_session.commit()
    assert super_admin.id is not None
    assert super_admin.tenant_id is None
    assert super_admin.tenant is None
