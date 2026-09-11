"""Pydantic request and response schemas for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TicketIntakeRequest(BaseModel):
    """New ticket content submitted for triage."""

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    category_hint: str | None = None


class TicketClassificationResponse(BaseModel):
    """Combined ML classification and business routing decision."""

    predicted_category: str
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
