"""Pydantic request and response schemas for the HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field

from models import TicketCategory

# ── Authentication schemas ────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """Payload for creating a new user account."""

    email: EmailStr
    password: str = Field(min_length=8, description="Must be at least 8 characters.")
    role: str = Field(default="user", description="Initial role assigned to the user.")
    tenant_id: str | None = Field(
        default=None,
        description="Tenant to enroll the user in. Omit for super-admin accounts.",
    )


class LoginRequest(BaseModel):
    """Credentials submitted during the login flow."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Returned upon successful authentication."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Public representation of the authenticated user."""

    id: str
    email: str
    role: str
    tenant_id: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class TicketIntakeRequest(BaseModel):
    """New ticket content submitted for triage."""

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    category_hint: TicketCategory | None = None


class TicketClassificationResponse(BaseModel):
    """Combined ML classification and business routing decision."""

    predicted_category: TicketCategory
    predicted_priority: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    should_escalate: bool
    assigned_queue: str
    requires_human_handoff: bool
    reasons: list[str]


class HealthCheckResponse(BaseModel):
    """Service readiness response."""

    status: str
    version: str
    models_loaded: bool


class ChatRequest(BaseModel):
    """User prompt or support question submitted to the helpdesk agent."""

    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    """Structured response produced by the helpdesk agent."""

    response: str
    route: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None
    sources: list[str] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None


class JobCreateRequest(BaseModel):
    """Customer-authenticated job creation request."""

    customer_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_skill: str = Field(min_length=1)
    service_area: str = Field(min_length=1)
    priority: str = "medium"
    scheduled_at: str | None = None


class TicketJobCreateRequest(BaseModel):
    """Request to create and assign a job from an existing customer ticket."""

    customer_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_skill: str = Field(min_length=1)
    service_area: str = Field(min_length=1)
    priority: str = "medium"
    scheduled_at: str | None = None


class JobLockRequest(BaseModel):
    """Customer identity for locking a customer-owned job."""

    customer_id: str = Field(min_length=1)


class EngineerAssignmentRequest(BaseModel):
    """Human operator request to assign an engineer to a job."""

    engineer_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)


class EmailDraftCreateRequest(BaseModel):
    """AI-generated draft that must enter human review before sending."""

    ticket_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    ai_draft: str = Field(min_length=1)


class CustomerInquiryDraftRequest(BaseModel):
    """Customer message that should receive an AI draft for human review."""

    customer_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    ticket_id: str | None = None
    title: str | None = None
    email_thread_id: str | None = None


class CustomerInquiryDraftResponse(BaseModel):
    """AI response draft stored for human review."""

    draft: dict[str, Any]
    agent_response: str
    route: str | None = None
    tool_name: str | None = None
    sources: list[str] = Field(default_factory=list)
    intent: str | None = None


class EmailDraftApprovalRequest(BaseModel):
    """Human review decision for an AI email draft."""

    reviewer: str = Field(min_length=1)
    edited_body: str | None = None


class EmailDraftRejectionRequest(BaseModel):
    """Human rejection decision for an AI email draft."""

    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EmailDraftSendRequest(BaseModel):
    """Human-triggered send request for an approved email draft."""

    sender: str = Field(min_length=1)


class TicketListResponse(BaseModel):
    """List of support tickets."""

    tickets: list[dict[str, Any]]


class JobListResponse(BaseModel):
    """List of customer jobs."""

    jobs: list[dict[str, Any]]


class CustomerListResponse(BaseModel):
    """List of customers."""

    customers: list[dict[str, Any]]


class EmailDraftListResponse(BaseModel):
    """List of email drafts."""

    drafts: list[dict[str, Any]]
