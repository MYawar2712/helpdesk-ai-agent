"""LangChain runnable for validated helpdesk ticket classification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompt_values import PromptValue
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda

from llm.client import LLMClient
from llm.structured_extract import JSONGeneratingClient, TicketClassification

_PROMPT_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "prompts" / "ticket_classifier"
)
_PROMPT_VERSIONS = frozenset({"v1", "v2", "v3"})
_SYSTEM_PROMPT = "You classify helpdesk tickets and return the requested JSON only."


class PromptNotFoundError(FileNotFoundError):
    """Raised when the selected ticket-classification prompt is unavailable."""


class TicketClassificationChain:
    """Compose a prompt, the Day 11 client, and a Pydantic output parser."""

    def __init__(
        self,
        *,
        prompt_version: str = "v3",
        llm_client: JSONGeneratingClient | None = None,
    ) -> None:
        self.prompt_version = prompt_version
        self._llm_client = llm_client
        self.parser = PydanticOutputParser(pydantic_object=TicketClassification)
        self.prompt = PromptTemplate.from_template(
            "{classification_prompt}\n\n"
            "{format_instructions}\n\n"
            "Classify this ticket:\n{ticket_text}"
        )
        self.chain = self.prompt | RunnableLambda(self._generate) | self.parser

    def invoke(self, ticket_text: str) -> TicketClassification:
        """Run the LangChain pipeline and return a validated classification."""
        if not ticket_text.strip():
            raise ValueError("ticket_text must not be empty")
        return self.chain.invoke(
            {
                "classification_prompt": self.load_prompt(),
                "format_instructions": self.parser.get_format_instructions(),
                "ticket_text": ticket_text,
            }
        )

    def load_prompt(self) -> str:
        """Load the configured Day 12 prompt without duplicating its contents."""
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

    def _generate(self, prompt_value: PromptValue) -> str:
        """Adapt the existing JSON client to a LangChain runnable output."""
        client = self._llm_client or LLMClient()
        response: dict[str, Any] = client.generate_json(
            _SYSTEM_PROMPT, prompt_value.to_string()
        )
        return json.dumps(response)
