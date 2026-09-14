"""Validated structured extraction for helpdesk ticket classification."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from llm.client import LLMClient, LLMResponseError


class TicketClassification(BaseModel):
    """The validated classification returned for a helpdesk ticket."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category: Literal[
        "technical", "billing", "scheduling", "warranty", "cancellation", "general"
    ]
    priority: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0.0, le=1.0)
    needs_escalation: bool


class StructuredOutputError(RuntimeError):
    """Raised when no LLM response passes structured-output validation."""


class JSONGeneratingClient(Protocol):
    """The portion of :class:`LLMClient` used by structured extraction."""

    def generate_json(
        self, system_prompt: str, user_prompt: str
    ) -> dict[str, object]: ...


_JSON_INSTRUCTIONS = """
Return only a JSON object with exactly these fields:
- category: one of technical, billing, scheduling, warranty, cancellation, general
- priority: one of low, medium, high
- confidence: a number from 0.0 to 1.0 inclusive
- needs_escalation: a JSON boolean (true or false)

Do not include markdown, an explanation, or any additional fields.
""".strip()


def extract_ticket_classification(
    ticket_text: str,
    prompt: str,
    *,
    llm_client: JSONGeneratingClient | None = None,
    max_retries: int = 2,
) -> TicketClassification:
    """Classify a ticket, retrying invalid JSON or schema-invalid responses.

    ``max_retries`` is the number of additional attempts after the initial request.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be greater than or equal to zero")

    client = llm_client or LLMClient()
    system_prompt = f"{prompt.strip()}\n\n{_JSON_INSTRUCTIONS}"
    user_prompt = ticket_text
    last_error: LLMResponseError | ValidationError | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.generate_json(system_prompt, user_prompt)
            return TicketClassification.model_validate(response)
        except (LLMResponseError, ValidationError) as error:
            last_error = error
            if attempt == max_retries:
                break
            user_prompt = (
                "The previous response was invalid. Return only a JSON object matching "
                "the required schema for this ticket:\n\n"
                f"{ticket_text}"
            )

    raise StructuredOutputError(
        f"LLM output did not match the ticket classification schema after "
        f"{max_retries + 1} attempt(s)"
    ) from last_error
