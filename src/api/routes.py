"""HTTP route handlers for the helpdesk service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from api.schemas import (
    HealthCheckResponse,
    TicketClassificationResponse,
    TicketIntakeRequest,
)
from rules.escalation_engine import EscalationEngine
from workers.tasks import process_ticket_async

router = APIRouter()


@router.post("/api/v1/tickets/{ticket_id}/process-async", status_code=202)
async def process_ticket(ticket_id: str) -> dict[str, str]:
    """Queue asynchronous classification and escalation processing."""

    task = process_ticket_async.delay(ticket_id)
    return {"task_id": task.id, "status": "queued"}


@router.get("/health", response_model=HealthCheckResponse)
async def health(request: Request) -> HealthCheckResponse:
    """Report whether the classifier is ready to serve requests."""

    classifier = getattr(request.app.state, "classifier", None)
    return HealthCheckResponse(
        status="ok" if classifier is not None else "degraded",
        version=request.app.version,
        models_loaded=classifier is not None,
    )


@router.post("/api/v1/tickets/classify", response_model=TicketClassificationResponse)
async def classify_ticket(
    payload: TicketIntakeRequest, request: Request
) -> TicketClassificationResponse:
    """Classify and route a newly submitted ticket."""

    classifier = getattr(request.app.state, "classifier", None)
    if classifier is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Model not ready")
    prediction = classifier.predict(f"{payload.title}. {payload.description}")
    result = EscalationEngine().evaluate_ticket_rules(
        {"ticket": payload.model_dump(), "open_invoices": []},
        {
            "category": prediction.category,
            "priority": prediction.priority,
            "confidence_score": prediction.confidence_score,
        },
    )
    return TicketClassificationResponse(
        predicted_category=prediction.category,
        predicted_priority=prediction.priority,
        confidence_score=prediction.confidence_score,
        should_escalate=result.should_escalate,
        assigned_queue=result.target_queue,
        requires_human_handoff=result.requires_human_handoff,
        reasons=result.reasons,
    )


@router.get("/api/v1/tickets/{ticket_id}/context")
async def ticket_context(ticket_id: str, request: Request) -> dict[str, Any]:
    """Return the complete SQL and transcript context for a ticket."""

    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Repository not ready")
    context = repository.get_complete_ticket_context(ticket_id)
    if context is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return context
