"""HTTP route handlers for the helpdesk service."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from agent.graph import HelpdeskAgent
from api.schemas import (
    ChatRequest,
    ChatResponse,
    CustomerInquiryDraftRequest,
    CustomerInquiryDraftResponse,
    EmailDraftApprovalRequest,
    EmailDraftCreateRequest,
    EmailDraftRejectionRequest,
    EmailDraftSendRequest,
    EngineerAssignmentRequest,
    HealthCheckResponse,
    JobCreateRequest,
    JobLockRequest,
    TicketClassificationResponse,
    TicketIntakeRequest,
    TicketJobCreateRequest,
)
from rules.escalation_engine import EscalationEngine
from services.operations import (
    AuthorizationError,
    BusinessRuleError,
    CustomerIdentity,
    HelpdeskOperationsService,
    infer_required_skill,
)
from utils.date_parser import parse_natural_datetime
from workers.tasks import process_ticket_async

router = APIRouter()


def _extract_sources(result: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    tool_result = result.get("tool_result") or None
    if result.get("rag_result"):
        rag_res = result["rag_result"]
        sources = [
            str(doc.metadata["source"])
            for doc in getattr(rag_res, "retrieved_chunks", [])
            if hasattr(doc, "metadata") and "source" in doc.metadata
        ]
    elif tool_result and isinstance(tool_result, dict):
        if "sources" in tool_result and isinstance(tool_result["sources"], list):
            sources = [str(s) for s in tool_result["sources"]]
        elif "source" in tool_result:
            sources = [str(tool_result["source"])]
    return sources


@router.get("/")
async def root() -> dict[str, str]:
    """Root health and service status endpoint."""
    return {
        "status": "ok",
        "message": "Helpdesk AI Agent API",
        "version": "0.1.0",
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Process a support question asynchronously via the LangGraph agent."""
    if not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message cannot be empty or whitespace only",
        )

    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        agent = HelpdeskAgent()

    try:
        result = await asyncio.to_thread(agent.invoke, payload.message)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {err}",
        ) from err

    response_text = result.get("final_response") or result.get("response") or ""
    tool_name = result.get("tool_name") or None
    tool_result = result.get("tool_result") or None
    route = result.get("route") or None

    return ChatResponse(
        response=response_text,
        route=route,
        tool_name=tool_name,
        tool_result=tool_result,
        sources=_extract_sources(result),
    )


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


def _operations(request: Request) -> HelpdeskOperationsService:
    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Repository not ready")
    return HelpdeskOperationsService(repository.sql_connection)


def _handle_operation_error(err: Exception) -> None:
    if isinstance(err, AuthorizationError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(err)) from err
    if isinstance(err, LookupError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    if isinstance(err, BusinessRuleError):
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    raise err


@router.post("/api/v1/jobs", status_code=201)
async def create_job(payload: JobCreateRequest, request: Request) -> dict[str, Any]:
    """Create a job for an authenticated customer."""
    try:
        return _operations(request).create_job(
            CustomerIdentity(customer_id=payload.customer_id),
            title=payload.title,
            description=payload.description,
            required_skill=payload.required_skill,
            service_area=payload.service_area,
            priority=payload.priority,
            scheduled_at=payload.scheduled_at,
        )
    except Exception as err:
        _handle_operation_error(err)
        raise


@router.post("/api/v1/tickets/{ticket_id}/create-job", status_code=201)
async def create_job_for_ticket(
    ticket_id: str, payload: TicketJobCreateRequest, request: Request
) -> dict[str, Any]:
    """Create a job for a customer ticket, auto-assign an engineer, or escalate."""
    try:
        return _operations(request).create_job_for_ticket(
            CustomerIdentity(customer_id=payload.customer_id),
            ticket_id=ticket_id,
            title=payload.title,
            description=payload.description,
            required_skill=payload.required_skill,
            service_area=payload.service_area,
            priority=payload.priority,
            scheduled_at=payload.scheduled_at,
        )
    except Exception as err:
        _handle_operation_error(err)
        raise


@router.post("/api/v1/jobs/{job_id}/lock")
async def lock_job(
    job_id: str, payload: JobLockRequest, request: Request
) -> dict[str, Any]:
    """Lock a customer-owned job in a validated backend operation."""
    try:
        return _operations(request).lock_job(
            CustomerIdentity(customer_id=payload.customer_id), job_id=job_id
        )
    except Exception as err:
        _handle_operation_error(err)
        raise


@router.post("/api/v1/support/jobs/{job_id}/assign-engineer")
async def assign_engineer(
    job_id: str, payload: EngineerAssignmentRequest, request: Request
) -> dict[str, Any]:
    """Assign an eligible engineer through a human support operation."""
    try:
        return _operations(request).assign_engineer(
            job_id=job_id,
            engineer_id=payload.engineer_id,
            reviewer=payload.reviewer,
        )
    except Exception as err:
        _handle_operation_error(err)
        raise


@router.post("/api/v1/support/email-drafts", status_code=201)
async def create_email_draft(
    payload: EmailDraftCreateRequest, request: Request
) -> dict[str, Any]:
    """Create an AI email draft that must be reviewed by a human."""
    try:
        return _operations(request).create_email_draft(
            ticket_id=payload.ticket_id,
            customer_id=payload.customer_id,
            ai_draft=payload.ai_draft,
        )
    except Exception as err:
        _handle_operation_error(err)
        raise


@router.post(
    "/api/v1/customer-inquiries/draft-reply",
    response_model=CustomerInquiryDraftResponse,
    status_code=201,
)
async def draft_customer_inquiry_reply(
    payload: CustomerInquiryDraftRequest, request: Request
) -> CustomerInquiryDraftResponse:
    """Generate an AI draft reply and store it for human review."""
    if not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message cannot be empty or whitespace only",
        )

    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        agent = HelpdeskAgent()

    ticket_id = payload.ticket_id
    if not ticket_id:
        title = payload.title or (
            payload.message[:40] + ("..." if len(payload.message) > 40 else "")
        )
        try:
            new_ticket = _operations(request).create_ticket(
                CustomerIdentity(customer_id=payload.customer_id),
                title=title,
                description=payload.message,
            )
            ticket_id = new_ticket["id"]
        except Exception as err:
            _handle_operation_error(err)
            raise

    inferred_skill = infer_required_skill(payload.message)

    schedule_keywords = (
        "schedule",
        "job lock",
        "lock job",
        "book",
        "appointment",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "tomorrow",
        "today",
        "next week",
        "at 9",
        "at 10",
        "at 11",
        "at 12",
        "at 1",
        "at 2",
        "at 3",
        "at 4",
        "at 5",
        "at 6",
        "at 7",
        "at 8",
    )
    lowered_msg = payload.message.lower()
    has_schedule_intent = inferred_skill is not None and any(
        kw in lowered_msg for kw in schedule_keywords
    )

    if has_schedule_intent:
        parsed_dt = parse_natural_datetime(payload.message)
        scheduled_at_iso = parsed_dt.isoformat() if parsed_dt else None

        if scheduled_at_iso and inferred_skill:
            try:
                job_result = _operations(request).create_job_for_ticket(
                    CustomerIdentity(customer_id=payload.customer_id),
                    ticket_id=ticket_id,
                    title=f"{inferred_skill} Service Visit",
                    description=payload.message,
                    required_skill=inferred_skill,
                    service_area="London",
                    scheduled_at=scheduled_at_iso,
                )
                job = job_result.get("job", {})
                job_id = job.get("id", "unknown")
                day_name = parsed_dt.strftime("%A") if parsed_dt else ""
                if parsed_dt:
                    time_str = parsed_dt.strftime("%I:%M %p").lstrip("0")
                else:
                    time_str = ""
                response_text = (
                    f"Great news! I've scheduled your {inferred_skill} "
                    f"service visit for {day_name} at {time_str}. "
                    f"Your job ID is {job_id}. An engineer has been "
                    f"assigned and will arrive at the scheduled time."
                )
                draft = _operations(request).create_email_draft(
                    ticket_id=ticket_id,
                    customer_id=payload.customer_id,
                    ai_draft=response_text,
                )
                return CustomerInquiryDraftResponse(
                    draft=draft,
                    agent_response=response_text,
                    route="respond",
                    tool_name="schedule_job",
                    sources=[],
                )
            except Exception as err:
                _handle_operation_error(err)

    job_context_str: str | None = None
    if inferred_skill is not None:
        job_context_str = (
            f"Inferred Service Need: '{inferred_skill}' repair/service. "
            "(Action: job created and engineer assigned on approval & send)."
        )

    result: dict[str, Any] = {
        "route": "handoff",
        "tool_name": None,
        "tool_result": {},
    }
    context_parts: list[str] = [
        f"Customer ID: {payload.customer_id}",
        f"Ticket ID: {ticket_id}",
        f"Message: {payload.message}",
    ]
    if job_context_str:
        context_parts.append(job_context_str)
    prompt = "\n".join(context_parts)

    try:
        result = await asyncio.to_thread(agent.invoke, prompt)
        response_text = result.get("final_response") or result.get("response") or ""
        if not response_text.strip():
            raise BusinessRuleError("agent did not produce a draft response")
    except Exception as err:
        if isinstance(err, AuthorizationError | LookupError | BusinessRuleError):
            _handle_operation_error(err)
            raise
        response_text = (
            "Thanks for your message. I need a human support teammate to review "
            "this request before we reply with details."
        )
        result["handoff_reason"] = f"Agent draft generation failed: {err}"

    try:
        draft = _operations(request).create_email_draft(
            ticket_id=ticket_id,
            customer_id=payload.customer_id,
            ai_draft=response_text,
        )
    except Exception as err:
        _handle_operation_error(err)
        raise

    return CustomerInquiryDraftResponse(
        draft=draft,
        agent_response=response_text,
        route=result.get("route") or None,
        tool_name=result.get("tool_name") or None,
        sources=_extract_sources(result),
    )


@router.post("/api/v1/support/email-drafts/{draft_id}/approve")
async def approve_email_draft(
    draft_id: str, payload: EmailDraftApprovalRequest, request: Request
) -> dict[str, Any]:
    """Approve an AI email draft after human review."""
    try:
        return _operations(request).approve_email_draft(
            draft_id=draft_id,
            reviewer=payload.reviewer,
            edited_body=payload.edited_body,
        )
    except Exception as err:
        _handle_operation_error(err)
        raise


@router.post("/api/v1/support/email-drafts/{draft_id}/reject")
async def reject_email_draft(
    draft_id: str, payload: EmailDraftRejectionRequest, request: Request
) -> dict[str, Any]:
    """Reject an AI email draft and keep it from being sent."""
    try:
        return _operations(request).reject_email_draft(
            draft_id=draft_id, reviewer=payload.reviewer, reason=payload.reason
        )
    except Exception as err:
        _handle_operation_error(err)
        raise


@router.post("/api/v1/support/email-drafts/{draft_id}/send")
async def send_email_draft(
    draft_id: str, payload: EmailDraftSendRequest, request: Request
) -> dict[str, Any]:
    """Send only an approved email draft."""
    try:
        return _operations(request).send_approved_email(
            draft_id=draft_id, sender=payload.sender
        )
    except Exception as err:
        _handle_operation_error(err)
        raise
