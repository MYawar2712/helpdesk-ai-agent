"""Service for LLM-backed ticket classification and persistence."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from db.data_layer import HelpdeskDataRepository
from llm.structured_extract import (
    JSONGeneratingClient,
    TicketClassification,
    extract_ticket_classification,
)

logger = logging.getLogger(__name__)

_PROMPT_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "prompts" / "ticket_classifier"
)
_PROMPT_VERSIONS = frozenset({"v1", "v2", "v3"})

StructuredExtractor = Callable[..., TicketClassification]


class PromptNotFoundError(FileNotFoundError):
    """Raised when the requested ticket-classification prompt is unavailable."""


class TicketClassifier:
    """Coordinate prompt loading, structured LLM extraction, and persistence."""

    def __init__(
        self,
        repository: HelpdeskDataRepository,
        *,
        prompt_version: str = "v3",
        llm_client: JSONGeneratingClient | None = None,
        extractor: StructuredExtractor = extract_ticket_classification,
    ) -> None:
        self.repository = repository
        self.prompt_version = prompt_version
        self.llm_client = llm_client
        self._extractor = extractor

    def classify(self, ticket_text: str) -> TicketClassification:
        """Return a validated classification for raw ticket text."""
        if not ticket_text.strip():
            raise ValueError("ticket_text must not be empty")

        logger.info("Starting LLM ticket classification")
        classification = self._extractor(
            ticket_text,
            self.load_prompt(),
            llm_client=self.llm_client,
        )
        logger.info("LLM ticket classification validated")
        return classification

    def classify_and_save(
        self, ticket_id: str, ticket_text: str
    ) -> TicketClassification:
        """Classify a ticket and persist only its validated result."""
        logger.info("Received ticket for classification: %s", ticket_id)
        classification = self.classify(ticket_text)
        self.repository.save_ticket_classification(ticket_id, classification)
        logger.info("Ticket classification saved: %s", ticket_id)
        return classification

    def load_prompt(self) -> str:
        """Load the configured Day 12 prompt from the project prompt directory."""
        if self.prompt_version not in _PROMPT_VERSIONS:
            raise PromptNotFoundError(
                f"Unknown ticket-classification prompt version: {self.prompt_version}"
            )
        prompt_path = _PROMPT_DIRECTORY / f"{self.prompt_version}.md"
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise PromptNotFoundError(
                f"Ticket-classification prompt does not exist: {prompt_path}"
            ) from error
