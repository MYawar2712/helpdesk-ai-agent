from __future__ import annotations

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from llm.client import LLMResponseError
from llm.structured_extract import (
    StructuredOutputError,
    TicketClassification,
    extract_ticket_classification,
)

VALID_RESPONSE = {
    "category": "technical",
    "priority": "high",
    "confidence": 0.95,
    "needs_escalation": True,
}


def test_valid_json_returns_validated_classification() -> None:
    client = Mock()
    client.generate_json.return_value = VALID_RESPONSE

    result = extract_ticket_classification(
        "The air conditioner stopped cooling.",
        "Classify this ticket.",
        llm_client=client,
    )

    assert result == TicketClassification(**VALID_RESPONSE)
    system_prompt, user_prompt = client.generate_json.call_args.args
    assert "Return only a JSON object" in system_prompt
    assert user_prompt == "The air conditioner stopped cooling."


def test_invalid_json_retries() -> None:
    client = Mock()
    client.generate_json.side_effect = [
        LLMResponseError("invalid JSON"),
        VALID_RESPONSE,
    ]

    result = extract_ticket_classification("Ticket", "Classify.", llm_client=client)

    assert result.category == "technical"
    assert client.generate_json.call_count == 2
    assert "previous response was invalid" in client.generate_json.call_args.args[1]


def test_invalid_category_retries_then_succeeds() -> None:
    client = Mock()
    client.generate_json.side_effect = [
        {**VALID_RESPONSE, "category": "something_else"},
        VALID_RESPONSE,
    ]

    result = extract_ticket_classification("Ticket", "Classify.", llm_client=client)

    assert result.category == "technical"
    assert client.generate_json.call_count == 2


def test_invalid_confidence_retries_then_succeeds() -> None:
    client = Mock()
    client.generate_json.side_effect = [
        {**VALID_RESPONSE, "confidence": 1.7},
        VALID_RESPONSE,
    ]

    result = extract_ticket_classification("Ticket", "Classify.", llm_client=client)

    assert result.confidence == 0.95
    assert client.generate_json.call_count == 2


def test_retry_exhaustion_raises_and_limits_calls() -> None:
    client = Mock()
    client.generate_json.return_value = {**VALID_RESPONSE, "priority": "urgent"}

    with pytest.raises(StructuredOutputError, match="after 3 attempt") as error:
        extract_ticket_classification(
            "Ticket", "Classify.", llm_client=client, max_retries=2
        )

    assert isinstance(error.value.__cause__, ValidationError)
    assert client.generate_json.call_count == 3


def test_negative_max_retries_is_rejected() -> None:
    with pytest.raises(ValueError, match="greater than or equal to zero"):
        extract_ticket_classification("Ticket", "Classify.", max_retries=-1)
