"""Pydantic DTO schemas for Client Dashboard & Management APIs (Day 4)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

# ── Summary DTO ───────────────────────────────────────────────────────────────


class DashboardSummaryResponse(BaseModel):
    """Aggregate dashboard counters for tenant overview."""

    customers: int = Field(ge=0)
    open_tickets: int = Field(ge=0)
    active_jobs: int = Field(ge=0)
    pending_invoices: int = Field(ge=0)
    available_engineers: int = Field(ge=0)


# ── Customer DTOs ─────────────────────────────────────────────────────────────


class CustomerResponse(BaseModel):
    """Public customer model."""

    id: str
    tenant_id: str
    name: str
    email: str
    phone: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomerCreateRequest(BaseModel):
    """Payload to create a new customer."""

    name: str = Field(min_length=1)
    email: EmailStr
    phone: str = Field(min_length=1)


class CustomerUpdateRequest(BaseModel):
    """Payload to update an existing customer."""

    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None


# ── Engineer DTOs ─────────────────────────────────────────────────────────────


class EngineerResponse(BaseModel):
    """Public engineer model."""

    id: str
    tenant_id: str
    name: str
    email: str
    skills: list[str]
    availability_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EngineerCreateRequest(BaseModel):
    """Payload to create a new engineer."""

    name: str = Field(min_length=1)
    email: EmailStr
    skills: list[str] = Field(default_factory=list)
    availability_status: str = Field(default="available")


class EngineerUpdateRequest(BaseModel):
    """Payload to update an existing engineer."""

    name: str | None = None
    email: EmailStr | None = None
    skills: list[str] | None = None
    availability_status: str | None = None


# ── Ticket DTOs ───────────────────────────────────────────────────────────────


class TicketResponse(BaseModel):
    """Public ticket model."""

    id: str
    tenant_id: str
    customer_id: str
    related_job_id: str | None
    intent: str
    status: str
    priority: str
    handled_by: str
    resolution: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None

    model_config = {"from_attributes": True}


class TicketCreateDTO(BaseModel):
    """Payload to create a new ticket."""

    customer_id: str = Field(min_length=1)
    intent: str = Field(default="GENERAL_INQUIRY")
    priority: str = Field(default="medium")
    related_job_id: str | None = None


class TicketUpdateDTO(BaseModel):
    """Payload to update an existing ticket."""

    status: str | None = None
    priority: str | None = None
    handled_by: str | None = None
    resolution: str | None = None


# ── Job DTOs ──────────────────────────────────────────────────────────────────


class JobResponse(BaseModel):
    """Public job model."""

    id: str
    tenant_id: str
    customer_id: str
    title: str
    description: str
    status: str
    priority: str
    assigned_engineer_id: str | None
    scheduled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobCreateDTO(BaseModel):
    """Payload to create a new job."""

    customer_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    priority: str = Field(default="medium")
    assigned_engineer_id: str | None = None
    scheduled_at: datetime | None = None


class JobUpdateDTO(BaseModel):
    """Payload to update an existing job."""

    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assigned_engineer_id: str | None = None
    scheduled_at: datetime | None = None


class JobAssignDTO(BaseModel):
    """Payload to assign an engineer to a job."""

    engineer_id: str = Field(min_length=1)


# ── Invoice DTOs ──────────────────────────────────────────────────────────────


class InvoiceResponse(BaseModel):
    """Public invoice model."""

    id: str
    tenant_id: str
    customer_id: str
    job_id: str
    amount: Decimal
    status: str
    due_date: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceCreateDTO(BaseModel):
    """Payload to create a new invoice."""

    customer_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    due_date: datetime


class InvoiceUpdateDTO(BaseModel):
    """Payload to update an existing invoice."""

    amount: Decimal | None = Field(default=None, gt=0)
    status: str | None = None
    due_date: datetime | None = None


# ── Chat / Conversation DTOs (Day 5) ─────────────────────────────────────────


class ConversationCreateRequest(BaseModel):
    """Payload to open a new chat conversation."""

    subject: str = Field(default="", max_length=255, description="Optional subject.")
    ticket_id: str | None = Field(
        default=None, description="Optional linked ticket ID."
    )


class ConversationResponse(BaseModel):
    """Public representation of a conversation thread."""

    conversation_id: str
    tenant_id: str
    customer_id: str
    ticket_id: str | None
    subject: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """A single message inside a conversation."""

    message_id: str
    conversation_id: str
    sender_type: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    """Conversation with its full message history."""

    conversation_id: str
    tenant_id: str
    customer_id: str
    ticket_id: str | None
    subject: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]

    model_config = {"from_attributes": True}


class SendMessageRequest(BaseModel):
    """Payload to send a customer message into a conversation."""

    content: str = Field(..., min_length=1, description="Customer message text.")


class SendMessageResponse(BaseModel):
    """Response returned after a customer message is processed by the AI."""

    conversation_id: str
    message_id: str
    sender: str
    content: str
    created_at: datetime
