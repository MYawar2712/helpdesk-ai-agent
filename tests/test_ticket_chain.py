from __future__ import annotations

from unittest.mock import Mock

import pytest
from langchain_core.exceptions import OutputParserException

from chains.ticket_chain import TicketClassificationChain
from llm.structured_extract import TicketClassification

VALID_RESPONSE = {
    "category": "technical",
    "priority": "high",
    "confidence": 0.95,
    "needs_escalation": True,
}


def test_chain_returns_valid_ticket_classification() -> None:
    client = Mock()
    client.generate_json.return_value = VALID_RESPONSE
    chain = TicketClassificationChain(llm_client=client)

    result = chain.invoke("My air conditioner stopped working.")

    assert result == TicketClassification(**VALID_RESPONSE)


def test_chain_parser_rejects_invalid_llm_output() -> None:
    client = Mock()
    client.generate_json.return_value = {**VALID_RESPONSE, "priority": "urgent"}
    chain = TicketClassificationChain(llm_client=client)

    with pytest.raises(OutputParserException):
        chain.invoke("My air conditioner stopped working.")


def test_pydantic_output_parser_returns_ticket_classification() -> None:
    chain = TicketClassificationChain(llm_client=Mock())

    result = chain.parser.invoke(
        '{"category":"billing","priority":"medium",'
        '"confidence":0.8,"needs_escalation":false}'
    )

    assert isinstance(result, TicketClassification)
    assert result.category == "billing"


def test_chain_formats_existing_prompt_and_ticket_text() -> None:
    client = Mock()
    client.generate_json.return_value = VALID_RESPONSE
    chain = TicketClassificationChain(prompt_version="v2", llm_client=client)

    chain.invoke("I was charged twice for my service.")

    system_prompt, user_prompt = client.generate_json.call_args.args
    assert "JSON only" in system_prompt
    assert "I was charged twice for my service." in user_prompt
    assert "charged twice for my invoice" in user_prompt
    assert '"needs_escalation"' in user_prompt


def test_empty_ticket_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        TicketClassificationChain(llm_client=Mock()).invoke("  ")
