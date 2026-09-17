"""Unit tests for Day 19 RAG Pipeline, Retrieval, Generation, and Grounding."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from agent.rag_node import (
    SAFE_FALLBACK_RESPONSE,
    GroundingChecker,
    RAGGenerator,
    RAGNode,
    RAGResult,
    RAGRetriever,
    chunk_documents,
)


class MockLLMClient:
    """Deterministic mock LLM for testing RAG generation and grounding self-check."""

    def __init__(
        self,
        text_response: str = "To repressurize boiler, use filling loop until 1.5 bar.",
        json_response: dict[str, Any] | None = None,
    ) -> None:
        self.text_response = text_response
        self.json_response = json_response or {
            "is_grounded": True,
            "reason": "Answer matches knowledge base context.",
        }
        self.captured_prompts: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.captured_prompts.append((system_prompt, user_prompt))
        return self.text_response

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.captured_prompts.append((system_prompt, user_prompt))
        return self.json_response


def test_chunk_documents() -> None:
    """Test chunking long documents into smaller semantic chunks with metadata."""
    long_text = "Word " * 200
    doc = Document(
        page_content=long_text,
        metadata={"source": "boiler.md", "title": "Boiler Manual"},
    )
    chunks = chunk_documents([doc], chunk_size=100, chunk_overlap=20)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.metadata["source"] == "boiler.md"
        assert chunk.metadata["title"] == "Boiler Manual"


def test_relevant_documents_retrieved() -> None:
    """Test vector retriever queries vector store and retrieves relevant documents."""
    mock_chunks = [
        Document(
            page_content="Boiler pressure should be between 1.0 and 1.5 bar.",
            metadata={"source": "boiler.md", "title": "Boiler Pressure"},
        )
    ]
    with patch(
        "agent.rag_node.search_knowledge_base", return_value=mock_chunks
    ) as mock_search:
        retriever = RAGRetriever(k=2)
        retrieved = retriever.retrieve("how to fix low boiler pressure")

        assert len(retrieved) == 1
        assert "1.0 and 1.5 bar" in retrieved[0].page_content
        mock_search.assert_called_once()


def test_retriever_falls_back_to_keyword_search_when_vector_search_fails() -> None:
    """Local KB keyword search answers when Chroma/embeddings are unavailable."""
    with patch("agent.rag_node.search_knowledge_base", side_effect=RuntimeError):
        retriever = RAGRetriever(k=2)
        retrieved = retriever.retrieve("burning smell from my AC")

    assert retrieved
    assert retrieved[0].metadata["source"] == "electrical_safety.md"


def test_retrieved_context_reaches_llm() -> None:
    """Test retrieved chunks are properly formatted and injected into LLM prompt."""
    mock_llm = MockLLMClient()
    generator = RAGGenerator(llm_client=mock_llm)

    chunks = [
        Document(
            page_content="Turn the blue valve clockwise.",
            metadata={"source": "valve.md", "title": "Valve Controls"},
        )
    ]
    answer = generator.generate_answer("How to turn valve?", chunks)

    assert answer == "To repressurize boiler, use filling loop until 1.5 bar."
    assert len(mock_llm.captured_prompts) == 1
    sys_prompt, user_prompt = mock_llm.captured_prompts[0]
    assert "Turn the blue valve clockwise." in user_prompt
    assert "[Source 1: Valve Controls (valve.md)]" in user_prompt
    assert "How to turn valve?" in user_prompt


def test_grounded_answer_returned() -> None:
    """Test RAGNode pipeline completes successfully when answer is grounded."""
    mock_chunks = [
        Document(
            page_content="Boiler pressure filling loop instructions...",
            metadata={"source": "boiler.md", "title": "Boiler Help"},
        )
    ]
    mock_retriever = MagicMock(spec=RAGRetriever)
    mock_retriever.retrieve.return_value = mock_chunks

    mock_llm = MockLLMClient(
        text_response="Fill the boiler using the filling loop until 1.5 bar.",
        json_response={"is_grounded": True, "reason": "Fully grounded in article."},
    )
    generator = RAGGenerator(llm_client=mock_llm)
    grounding_checker = GroundingChecker(llm_client=mock_llm)

    node = RAGNode(
        retriever=mock_retriever,
        generator=generator,
        grounding_checker=grounding_checker,
    )
    result = node.run("How do I fix boiler pressure?")

    assert isinstance(result, RAGResult)
    assert not result.is_fallback
    assert result.is_grounded
    assert (
        result.final_response == "Fill the boiler using the filling loop until 1.5 bar."
    )
    assert result.grounding_reason == "Fully grounded in article."


def test_insufficient_context_handled() -> None:
    """Test insufficient context (empty retrieval) returns safe fallback response."""
    mock_retriever = MagicMock(spec=RAGRetriever)
    mock_retriever.retrieve.return_value = []

    mock_llm = MockLLMClient()
    generator = RAGGenerator(llm_client=mock_llm)
    grounding_checker = GroundingChecker(llm_client=mock_llm)

    node = RAGNode(
        retriever=mock_retriever,
        generator=generator,
        grounding_checker=grounding_checker,
    )
    result = node.run("What is quantum quantum magic?")

    assert result.is_fallback
    assert not result.is_grounded
    assert result.final_response == SAFE_FALLBACK_RESPONSE
    assert result.retrieved_chunks == []


def test_ungrounded_answer_rejected() -> None:
    """Test ungrounded answer is rejected and replaced with safe fallback response."""
    mock_chunks = [
        Document(
            page_content="Our warranty covers heating element parts for 2 years.",
            metadata={"source": "warranty.md", "title": "Warranty Policy"},
        )
    ]
    mock_retriever = MagicMock(spec=RAGRetriever)
    mock_retriever.retrieve.return_value = mock_chunks

    mock_llm = MockLLMClient(
        text_response="We offer a 100-year unlimited free warranty for all products.",
        json_response={
            "is_grounded": False,
            "reason": "100-year unlimited warranty claim is unsupported by context.",
        },
    )
    generator = RAGGenerator(llm_client=mock_llm)
    grounding_checker = GroundingChecker(llm_client=mock_llm)

    node = RAGNode(
        retriever=mock_retriever,
        generator=generator,
        grounding_checker=grounding_checker,
    )
    result = node.run("What is the warranty period?")

    assert not result.is_fallback  # chunks retrieved -> candidate answer returned
    assert not result.is_grounded  # grounding check still recorded as failed
    assert result.final_response == (
        "We offer a 100-year unlimited free warranty for all products."
    )
    assert (
        result.grounding_reason
        == "100-year unlimited warranty claim is unsupported by context."
    )
