"""Multi-Tenant Service Layer enforcing strict tenant data isolation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    AIConfiguration,
    AuditLog,
    Conversation,
    Customer,
    Engineer,
    Invoice,
    Job,
    KnowledgeDocument,
    Message,
    Tenant,
    Ticket,
)


class CrossTenantAccessError(PermissionError):
    """Raised when an action attempts cross-tenant access or invalid entity linkage."""

    pass


class TenantDataService:
    """Service layer enforcing tenant isolation across all domain entities."""

    def __init__(self, session: Session, tenant_id: str | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Tenant Management
    # ------------------------------------------------------------------

    def create_tenant(self, name: str, slug: str) -> Tenant:
        tenant = Tenant(name=name, slug=slug)
        self.session.add(tenant)
        self.session.commit()
        self.session.refresh(tenant)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self.session.scalar(select(Tenant).where(Tenant.id == tenant_id))

    def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        return self.session.scalar(select(Tenant).where(Tenant.slug == slug))

    # ------------------------------------------------------------------
    # Customer Operations
    # ------------------------------------------------------------------

    def create_customer(
        self, tenant_id: str, name: str, email: str, phone: str
    ) -> Customer:
        self._validate_tenant_access(tenant_id)
        customer = Customer(
            tenant_id=tenant_id,
            name=name,
            email=email,
            phone=phone,
        )
        self.session.add(customer)
        self.session.commit()
        self.session.refresh(customer)
        return customer

    def get_customer(self, tenant_id: str, customer_id: str) -> Customer | None:
        self._validate_tenant_access(tenant_id)
        return self.session.scalar(
            select(Customer).where(
                Customer.id == customer_id, Customer.tenant_id == tenant_id
            )
        )

    def list_customers(self, tenant_id: str) -> list[Customer]:
        self._validate_tenant_access(tenant_id)
        return list(
            self.session.scalars(
                select(Customer).where(Customer.tenant_id == tenant_id)
            ).all()
        )

    # ------------------------------------------------------------------
    # Engineer Operations
    # ------------------------------------------------------------------

    def create_engineer(
        self,
        tenant_id: str,
        name: str,
        email: str,
        skills: list[str] | None = None,
        availability_status: str = "available",
    ) -> Engineer:
        self._validate_tenant_access(tenant_id)
        engineer = Engineer(
            tenant_id=tenant_id,
            name=name,
            email=email,
            skills=skills or [],
            availability_status=availability_status,
        )
        self.session.add(engineer)
        self.session.commit()
        self.session.refresh(engineer)
        return engineer

    def get_engineer(self, tenant_id: str, engineer_id: str) -> Engineer | None:
        self._validate_tenant_access(tenant_id)
        return self.session.scalar(
            select(Engineer).where(
                Engineer.id == engineer_id, Engineer.tenant_id == tenant_id
            )
        )

    # ------------------------------------------------------------------
    # Job Operations
    # ------------------------------------------------------------------

    def create_job(
        self,
        tenant_id: str,
        customer_id: str,
        title: str,
        description: str,
        status: str = "pending",
        priority: str = "medium",
        assigned_engineer_id: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> Job:
        self._validate_tenant_access(tenant_id)
        customer = self.get_customer(tenant_id, customer_id)
        if not customer:
            raise CrossTenantAccessError(
                f"Customer {customer_id} does not exist for tenant {tenant_id}"
            )

        if assigned_engineer_id:
            engineer = self.get_engineer(tenant_id, assigned_engineer_id)
            if not engineer:
                raise CrossTenantAccessError(
                    f"Engineer {assigned_engineer_id} does not exist for tenant "
                    f"{tenant_id}"
                )

        job = Job(
            tenant_id=tenant_id,
            customer_id=customer_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assigned_engineer_id=assigned_engineer_id,
            scheduled_at=scheduled_at,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def get_job(self, tenant_id: str, job_id: str) -> Job | None:
        self._validate_tenant_access(tenant_id)
        return self.session.scalar(
            select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
        )

    def list_jobs(self, tenant_id: str, customer_id: str | None = None) -> list[Job]:
        self._validate_tenant_access(tenant_id)
        stmt = select(Job).where(Job.tenant_id == tenant_id)
        if customer_id:
            stmt = stmt.where(Job.customer_id == customer_id)
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # Ticket Operations
    # ------------------------------------------------------------------

    def create_ticket(
        self,
        tenant_id: str,
        customer_id: str,
        title: str,
        description: str,
        related_job_id: str | None = None,
        intent: str = "GENERAL_INQUIRY",
        status: str = "open",
        priority: str = "medium",
        handled_by: str = "PENDING",
        resolution: str | None = None,
    ) -> Ticket:
        self._validate_tenant_access(tenant_id)
        customer = self.get_customer(tenant_id, customer_id)
        if not customer:
            raise CrossTenantAccessError(
                f"Customer {customer_id} does not exist for tenant {tenant_id}"
            )

        if related_job_id:
            job = self.get_job(tenant_id, related_job_id)
            if not job:
                raise CrossTenantAccessError(
                    f"Job {related_job_id} does not exist for tenant {tenant_id}"
                )

        ticket = Ticket(
            tenant_id=tenant_id,
            customer_id=customer_id,
            related_job_id=related_job_id,
            intent=intent,
            status=status,
            priority=priority,
            handled_by=handled_by,
            resolution=resolution,
        )
        self.session.add(ticket)
        self.session.commit()
        self.session.refresh(ticket)
        return ticket

    def get_ticket(self, tenant_id: str, ticket_id: str) -> Ticket | None:
        self._validate_tenant_access(tenant_id)
        return self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        )

    def list_tickets(
        self, tenant_id: str, customer_id: str | None = None
    ) -> list[Ticket]:
        self._validate_tenant_access(tenant_id)
        stmt = select(Ticket).where(Ticket.tenant_id == tenant_id)
        if customer_id:
            stmt = stmt.where(Ticket.customer_id == customer_id)
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # Invoice Operations
    # ------------------------------------------------------------------

    def create_invoice(
        self,
        tenant_id: str,
        customer_id: str,
        job_id: str,
        amount: Decimal,
        due_date: datetime,
        status: str = "unpaid",
    ) -> Invoice:
        self._validate_tenant_access(tenant_id)
        customer = self.get_customer(tenant_id, customer_id)
        if not customer:
            raise CrossTenantAccessError(
                f"Customer {customer_id} does not exist for tenant {tenant_id}"
            )

        job = self.get_job(tenant_id, job_id)
        if not job:
            raise CrossTenantAccessError(
                f"Job {job_id} does not exist for tenant {tenant_id}"
            )

        invoice = Invoice(
            tenant_id=tenant_id,
            customer_id=customer_id,
            job_id=job_id,
            amount=amount,
            due_date=due_date,
            status=status,
        )
        self.session.add(invoice)
        self.session.commit()
        self.session.refresh(invoice)
        return invoice

    def get_invoice(self, tenant_id: str, invoice_id: str) -> Invoice | None:
        self._validate_tenant_access(tenant_id)
        return self.session.scalar(
            select(Invoice).where(
                Invoice.id == invoice_id, Invoice.tenant_id == tenant_id
            )
        )

    def list_invoices(
        self, tenant_id: str, customer_id: str | None = None
    ) -> list[Invoice]:
        self._validate_tenant_access(tenant_id)
        stmt = select(Invoice).where(Invoice.tenant_id == tenant_id)
        if customer_id:
            stmt = stmt.where(Invoice.customer_id == customer_id)
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    # Conversation & Message Operations
    # ------------------------------------------------------------------

    def create_conversation(
        self,
        tenant_id: str,
        customer_id: str,
        ticket_id: str | None = None,
        subject: str = "",
        status: str = "open",
    ) -> Conversation:
        self._validate_tenant_access(tenant_id)
        customer = self.get_customer(tenant_id, customer_id)
        if not customer:
            raise CrossTenantAccessError(
                f"Customer {customer_id} does not exist for tenant {tenant_id}"
            )

        if ticket_id:
            ticket = self.get_ticket(tenant_id, ticket_id)
            if not ticket:
                raise CrossTenantAccessError(
                    f"Ticket {ticket_id} does not exist for tenant {tenant_id}"
                )

        conversation = Conversation(
            tenant_id=tenant_id,
            customer_id=customer_id,
            ticket_id=ticket_id,
            subject=subject,
            status=status,
        )
        self.session.add(conversation)
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def get_conversation(
        self, tenant_id: str, conversation_id: str
    ) -> Conversation | None:
        self._validate_tenant_access(tenant_id)
        return self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )

    def add_message(
        self,
        tenant_id: str,
        conversation_id: str,
        sender_type: str,
        content: str,
    ) -> Message:
        self._validate_tenant_access(tenant_id)
        conversation = self.get_conversation(tenant_id, conversation_id)
        if not conversation:
            raise CrossTenantAccessError(
                f"Conversation {conversation_id} does not exist for tenant {tenant_id}"
            )

        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sender_type=sender_type,
            content=content,
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def get_messages(self, tenant_id: str, conversation_id: str) -> list[Message]:
        self._validate_tenant_access(tenant_id)
        conversation = self.get_conversation(tenant_id, conversation_id)
        if not conversation:
            return []
        return list(
            self.session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.tenant_id == tenant_id,
                )
                .order_by(Message.created_at.asc())
            ).all()
        )

    # ------------------------------------------------------------------
    # AI Configuration Operations
    # ------------------------------------------------------------------

    def set_ai_configuration(
        self,
        tenant_id: str,
        global_instructions: str | None = None,
        tone: str | None = None,
        escalation_rules: Any | None = None,
        business_rules: Any | None = None,
    ) -> AIConfiguration:
        self._validate_tenant_access(tenant_id)
        config = self.session.scalar(
            select(AIConfiguration).where(AIConfiguration.tenant_id == tenant_id)
        )
        if config is None:
            config = AIConfiguration(
                tenant_id=tenant_id,
                global_instructions=global_instructions,
                tone=tone,
                escalation_rules=escalation_rules,
                business_rules=business_rules,
            )
            self.session.add(config)
        else:
            if global_instructions is not None:
                config.global_instructions = global_instructions
            if tone is not None:
                config.tone = tone
            if escalation_rules is not None:
                config.escalation_rules = escalation_rules
            if business_rules is not None:
                config.business_rules = business_rules
            config.updated_at = datetime.now(UTC)

        self.session.commit()
        self.session.refresh(config)
        return config

    def get_ai_configuration(self, tenant_id: str) -> AIConfiguration | None:
        self._validate_tenant_access(tenant_id)
        return self.session.scalar(
            select(AIConfiguration).where(AIConfiguration.tenant_id == tenant_id)
        )

    # ------------------------------------------------------------------
    # Knowledge Document Operations
    # ------------------------------------------------------------------

    def create_knowledge_document(
        self,
        tenant_id: str,
        name: str,
        file_path: str | None = None,
        processing_status: str = "pending",
        doc_metadata: Any | None = None,
    ) -> KnowledgeDocument:
        self._validate_tenant_access(tenant_id)
        doc = KnowledgeDocument(
            tenant_id=tenant_id,
            name=name,
            file_path=file_path,
            processing_status=processing_status,
            doc_metadata=doc_metadata,
        )
        self.session.add(doc)
        self.session.commit()
        self.session.refresh(doc)
        return doc

    def list_knowledge_documents(self, tenant_id: str) -> list[KnowledgeDocument]:
        self._validate_tenant_access(tenant_id)
        return list(
            self.session.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.tenant_id == tenant_id
                )
            ).all()
        )

    # ------------------------------------------------------------------
    # Audit Log Operations
    # ------------------------------------------------------------------

    def create_audit_log(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        result: str = "success",
        metadata_json: Any | None = None,
    ) -> AuditLog:
        effective_tenant_id = tenant_id or self.tenant_id
        if effective_tenant_id:
            self._validate_tenant_access(effective_tenant_id)

        log = AuditLog(
            tenant_id=effective_tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            metadata_json=metadata_json,
        )
        self.session.add(log)
        self.session.commit()
        self.session.refresh(log)
        return log

    # ------------------------------------------------------------------
    # Internal Validation Helper
    # ------------------------------------------------------------------

    def _validate_tenant_access(self, target_tenant_id: str) -> None:
        """Validate target_tenant_id matches authenticated tenant_id if bound."""
        if self.tenant_id is not None and self.tenant_id != target_tenant_id:
            raise CrossTenantAccessError(
                f"Unauthorized cross-tenant access attempt: active tenant is "
                f"'{self.tenant_id}', target tenant is '{target_tenant_id}'"
            )
