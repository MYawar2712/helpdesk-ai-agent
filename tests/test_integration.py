"""Week 3 Integration tests covering tools, RAG, agent routing, and FastAPI /chat."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from agent.graph import HelpdeskAgent
from agent.rag_node import RAGNode, RAGResult
from api.main import app


def test_integration_tool_based_request() -> None:
    """Test agent correctly routes and executes get_job database tool."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "route": "tool",
        "tool_name": "get_job",
        "tool_input": {"id": "123"},
    }
    mock_llm.generate.return_value = "Job 123 is currently in progress."

    mock_tool = MagicMock()
    mock_tool.name = "get_job"
    mock_tool.invoke.return_value = {"job": {"id": "123", "status": "in_progress"}}

    agent = HelpdeskAgent(llm_client=mock_llm, tools=[mock_tool])
    result = agent.invoke("What is the status of job 123?")

    assert result["route"] == "tool"
    assert result["tool_name"] == "get_job"
    assert result["final_response"] == "Job 123 is currently in progress."
    mock_tool.invoke.assert_called_once_with({"id": "123"})


def test_integration_rag_based_request() -> None:
    """Test agent correctly routes to RAG node for knowledge-base questions."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {"route": "rag"}

    mock_rag_node = MagicMock(spec=RAGNode)
    mock_rag_node.run.return_value = RAGResult(
        query="What is your warranty policy?",
        retrieved_chunks=[
            Document(
                page_content="Our warranty covers 2 years of parts.",
                metadata={"source": "warranty_coverage.md"},
            )
        ],
        candidate_answer="Our warranty covers 2 years of parts.",
        is_grounded=True,
        grounding_reason="Directly backed by warranty_coverage.md",
        final_response="Our warranty covers 2 years of parts.",
        is_fallback=False,
    )

    agent = HelpdeskAgent(llm_client=mock_llm, rag_node=mock_rag_node)
    result = agent.invoke("What is your warranty policy?")

    assert result["route"] == "rag"
    assert result["final_response"] == "Our warranty covers 2 years of parts."
    mock_rag_node.run.assert_called_once_with("What is your warranty policy?")


def test_integration_normal_request() -> None:
    """Test general greetings are answered directly by agent's respond route."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "route": "respond",
        "response": "Hello! How can I assist you with your helpdesk request today?",
    }

    agent = HelpdeskAgent(llm_client=mock_llm)
    result = agent.invoke("Hello support team")

    assert result["route"] == "respond"
    assert "Hello!" in result["final_response"]


def test_integration_invalid_chat_request() -> None:
    """Test FastAPI /chat endpoint rejects missing/empty message with HTTP 422."""
    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "   "})
    assert response.status_code == 422


def test_integration_tool_failure_handling() -> None:
    """Test tool errors or invalid tools raise errors cleanly."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "route": "tool",
        "tool_name": "unknown_tool",
        "tool_input": {},
    }

    agent = HelpdeskAgent(llm_client=mock_llm, tools=[])
    with pytest.raises(ValueError, match="Unknown or unavailable tool"):
        agent.invoke("Run unknown tool")


def test_integration_rag_failure_fallback() -> None:
    """Test RAG fallback response when vector retriever finds no relevant context."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {"route": "rag"}

    mock_rag_node = MagicMock(spec=RAGNode)
    mock_rag_node.run.return_value = RAGResult(
        query="Unrelated topic",
        retrieved_chunks=[],
        candidate_answer="",
        is_grounded=False,
        grounding_reason="No context found.",
        final_response="I'm sorry, but I don't have enough information.",
        is_fallback=True,
    )

    agent = HelpdeskAgent(llm_client=mock_llm, rag_node=mock_rag_node)
    result = agent.invoke("Tell me a fairy tale")

    assert result["route"] == "rag"
    assert result["rag_result"].is_fallback
    assert "don't have enough information" in result["final_response"]


def test_integration_complete_chat_flow() -> None:
    """Test end-to-end HTTP POST /chat -> LangGraph Agent -> RAG -> Structured JSON."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {"route": "rag"}

    mock_rag_node = MagicMock(spec=RAGNode)
    mock_rag_node.run.return_value = RAGResult(
        query="How to fix low boiler pressure?",
        retrieved_chunks=[
            Document(
                page_content="Locate the filling loop to repressurize to 1.5 bar.",
                metadata={"source": "boiler_pressure_low.md"},
            )
        ],
        candidate_answer="Use filling loop to repressurize your boiler to 1.5 bar.",
        is_grounded=True,
        grounding_reason="Grounded in boiler_pressure_low.md",
        final_response="Use filling loop to repressurize your boiler to 1.5 bar.",
        is_fallback=False,
    )

    mock_agent = HelpdeskAgent(llm_client=mock_llm, rag_node=mock_rag_node)

    with TestClient(app) as client:
        app.state.agent = mock_agent
        response = client.post(
            "/chat",
            json={"message": "How to fix low boiler pressure?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert (
        data["response"] == "Use filling loop to repressurize your boiler to 1.5 bar."
    )
    assert data["route"] == "rag"
    assert "boiler_pressure_low.md" in data["sources"]
