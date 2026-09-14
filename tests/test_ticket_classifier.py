from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from llm.structured_extract import StructuredOutputError, TicketClassification
from services.ticket_classifier import PromptNotFoundError, TicketClassifier


def valid_classification(category: str = "technical") -> TicketClassification:
    return TicketClassification(
        category=category,
        priority="high",
        confidence=0.95,
        needs_escalation=True,
    )


def repository() -> HelpdeskDataRepository:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    return HelpdeskDataRepository(connection, NoSQLClient(sqlite3.connect(":memory:")))


def test_successful_classification_returns_validated_result() -> None:
    extractor = Mock(return_value=valid_classification())
    classifier = TicketClassifier(repository(), extractor=extractor)

    result = classifier.classify("My air conditioner stopped working.")

    assert result.category == "technical"
    assert extractor.call_args.args[0] == "My air conditioner stopped working."


@pytest.mark.parametrize(
    ("ticket_text", "category"),
    [
        ("I was charged twice for my service.", "billing"),
        ("Move my appointment from Monday to Wednesday.", "scheduling"),
    ],
)
def test_classifies_multiple_ticket_categories(ticket_text: str, category: str) -> None:
    classifier = TicketClassifier(
        repository(), extractor=Mock(return_value=valid_classification(category))
    )

    assert classifier.classify(ticket_text).category == category


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_prompt_versions_load_their_matching_files(version: str) -> None:
    classifier = TicketClassifier(repository(), prompt_version=version)

    assert classifier.load_prompt() == (
        Path("prompts") / "ticket_classifier" / f"{version}.md"
    ).read_text(encoding="utf-8")


def test_unknown_prompt_version_raises() -> None:
    with pytest.raises(PromptNotFoundError, match="Unknown"):
        TicketClassifier(repository(), prompt_version="v4").load_prompt()


def test_invalid_structured_output_is_not_saved() -> None:
    data_repository = repository()
    classifier = TicketClassifier(
        data_repository,
        extractor=Mock(side_effect=StructuredOutputError("invalid output")),
    )

    with pytest.raises(StructuredOutputError):
        classifier.classify_and_save("ticket-1", "Broken response")

    row = data_repository.sql_connection.execute(
        "SELECT confidence, needs_escalation FROM tickets WHERE id = 'ticket-1'"
    ).fetchone()
    assert tuple(row) == (None, None)


def test_complete_flow_persists_valid_classification() -> None:
    data_repository = repository()
    extractor = Mock(return_value=valid_classification("scheduling"))
    classifier = TicketClassifier(
        data_repository, prompt_version="v2", extractor=extractor
    )

    result = classifier.classify_and_save(
        "ticket-1", "My technician was supposed to arrive yesterday."
    )

    row = data_repository.sql_connection.execute(
        """SELECT category, priority, confidence, needs_escalation
        FROM tickets WHERE id = 'ticket-1'"""
    ).fetchone()
    assert result.category == "scheduling"
    assert tuple(row) == ("scheduling", "high", 0.95, 1)
    assert "charged twice" not in extractor.call_args.args[0]


def test_database_failure_is_surfaced() -> None:
    data_repository = Mock()
    data_repository.save_ticket_classification.side_effect = sqlite3.OperationalError(
        "database unavailable"
    )
    classifier = TicketClassifier(
        data_repository, extractor=Mock(return_value=valid_classification())
    )

    with pytest.raises(sqlite3.OperationalError, match="database unavailable"):
        classifier.classify_and_save("ticket-1", "The air conditioner stopped working.")
