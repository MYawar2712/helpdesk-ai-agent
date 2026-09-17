"""LangGraph agent for helpdesk decisions, tools, RAG, and human handoff."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from agent.rag_node import RAGNode
from agent.tracing import traceable
from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from llm.client import LLMClient
from tools.get_all_invoices import create_get_all_invoices_tool
from tools.get_customer import create_get_customer_tool
from tools.get_job import create_get_job_tool
from tools.get_open_invoices import create_get_open_invoices_tool
from tools.schedule_job import create_schedule_job_tool


class AgentState(TypedDict, total=False):
    """Shared state passed between every graph node."""

    ticket_text: str
    route: Literal["tool", "handoff", "respond", "rag"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_result: dict[str, Any]
    response: str
    handoff_reason: str
    final_response: str
    rag_result: Any
    predicted_category: str
    predicted_priority: str
    confidence_score: float


class AgentDecision(BaseModel):
    """Validated decision returned by the LLM decision node."""

    model_config = ConfigDict(extra="ignore")

    route: Literal["tool", "handoff", "respond", "rag"]
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    response: str | None = None
    handoff_reason: str | None = None


class DecisionClient(Protocol):
    """LLM methods required by the graph."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...

    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


def create_default_tools() -> list[BaseTool]:
    """Create default repository-backed tools for database lookups."""
    db_path = Path(__file__).resolve().parents[2] / "db" / "helpdesk.sqlite3"
    try:
        connection = sqlite3.connect(str(db_path), check_same_thread=False)
        repo = HelpdeskDataRepository(
            connection, NoSQLClient(sqlite3.connect(":memory:"))
        )
        return [
            create_get_job_tool(repo),
            create_get_customer_tool(repo),
            create_get_open_invoices_tool(repo),
            create_get_all_invoices_tool(repo),
            create_schedule_job_tool(),
        ]
    except Exception:
        return []


class HelpdeskAgent:
    """Compile and invoke the modular helpdesk LangGraph."""

    def __init__(
        self,
        *,
        llm_client: DecisionClient | None = None,
        tools: list[BaseTool] | None = None,
        rag_node: RAGNode | None = None,
    ) -> None:
        self._llm_client = llm_client
        active_tools = tools if tools is not None else create_default_tools()
        self._tools = {tool.name: tool for tool in active_tools}
        self._rag_node = rag_node
        self.graph = build_helpdesk_graph(
            self._decision_node,
            self._tool_node,
            self._handoff_node,
            self._rag_execution_node,
            self._final_node,
        )

    @traceable(name="helpdesk_agent")
    def invoke(self, ticket_text: str) -> AgentState:
        """Run the graph for one support ticket."""
        if not ticket_text.strip():
            raise ValueError("ticket_text must not be empty")
        return self.graph.invoke({"ticket_text": ticket_text})

    def _client(self) -> DecisionClient:
        return self._llm_client or LLMClient()

    @traceable(name="decide_node")
    def _decision_node(self, state: AgentState) -> AgentState:
        category = state.get("predicted_category")
        priority = state.get("predicted_priority")
        confidence = state.get("confidence_score", 1.0)
        if not category or not priority:
            try:
                from ml.classifier import TicketClassifier

                pred = TicketClassifier().predict(state["ticket_text"])
                category = pred.category
                priority = pred.priority
                confidence = pred.confidence_score
            except Exception:
                category, priority, confidence = "general_inquiry", "medium", 1.0

        dispute_keywords = (
            "refund",
            "chargeback",
            "legal",
            "overcharge",
            "double charge",
            "charged twice",
            "double charged",
            "billing issue",
            "billing dispute",
            "wrong charge",
            "incorrect charge",
            "unauthorized charge",
            "duplicate charge",
            "overcharged",
        )
        lowered = state["ticket_text"].lower()
        if any(k in lowered for k in dispute_keywords):
            return {
                **state,
                "predicted_category": category,
                "predicted_priority": priority,
                "confidence_score": confidence,
                "route": "handoff",
                "tool_name": "",
                "tool_input": {},
                "response": (
                    "I'm handing this ticket to human support. Reason: "
                    "Financial / billing dispute requires human intervention."
                ),
                "handoff_reason": (
                    "Financial / billing dispute requires human intervention"
                ),
            }

        decision_prompt = f"""You are a helpdesk routing decision maker.
Return JSON only.
ML Classification Context: Category={category}, Priority={priority},
Confidence={confidence:.2f}
Choose route 'tool' when database information (get_job, get_customer,
get_open_invoices, get_all_invoices) is needed. Use get_open_invoices for unpaid
or overdue invoices. Use get_all_invoices when all paid and unpaid invoices are
requested. Choose 'rag' when knowledge-base, policy, warranty, or technical
troubleshooting information is needed. Choose 'respond' when drafting a customer reply
or handling job requests, job locks, or service scheduling.
When the customer mentions a specific time for a job (e.g., "Monday at 9am",
"Friday at 3pm", "tomorrow at 10am"), use the schedule_job tool with the exact
scheduling text as input, then respond confirming the job will be scheduled for that
time.
When 'respond' is chosen for job locks or service requests with a specified time,
confirm directly that the job has been scheduled for that date/time. Do NOT ask the
customer to re-confirm the time. Choose 'handoff' ONLY for explicit safety emergencies
or non-standard human support escalations.
If Customer ID or Ticket ID is present in the input, include customer_id or id in
tool_input.
For tool, provide tool_name and tool_input. For handoff, provide handoff_reason.
For respond, provide response. Allowed tools: get_job, get_customer,
get_open_invoices, get_all_invoices, schedule_job."""

        decision_data = self._client().generate_json(
            decision_prompt,
            state["ticket_text"],
        )
        # Un-nest dictionary in tool_name if the LLM wrapped it
        if isinstance(decision_data.get("tool_name"), dict):
            inner = decision_data.pop("tool_name")
            if "tool_name" in inner:
                decision_data["tool_name"] = inner["tool_name"]
            if "tool_input" in inner and isinstance(inner["tool_input"], dict):
                decision_data["tool_input"] = inner["tool_input"]

        # Normalize equivalent responses missing route key or wrapping tool
        if "route" not in decision_data and "tool" in decision_data:
            tool_val = decision_data.pop("tool")
            if isinstance(tool_val, dict):
                decision_data["route"] = "tool"
                decision_data["tool_name"] = tool_val.get("tool_name") or tool_val.get(
                    "name"
                )
                decision_data["tool_input"] = (
                    tool_val.get("tool_input") or tool_val.get("input") or {}
                )
            else:
                decision_data["route"] = "tool"
                decision_data["tool_name"] = tool_val
        elif "route" not in decision_data and "tool_name" in decision_data:
            decision_data["route"] = "tool"

        decision = AgentDecision.model_validate(decision_data)
        if decision.route == "tool" and decision.tool_name not in self._tools:
            raise ValueError(f"Unknown or unavailable tool: {decision.tool_name}")
        return {
            **state,
            "predicted_category": category,
            "predicted_priority": priority,
            "confidence_score": confidence,
            "route": decision.route,
            "tool_name": decision.tool_name or "",
            "tool_input": decision.tool_input,
            "response": decision.response or "",
            "handoff_reason": decision.handoff_reason or "",
        }

    @traceable(name="tool_node")
    def _tool_node(self, state: AgentState) -> AgentState:
        tool = self._tools[state["tool_name"]]
        tool_input = dict(state.get("tool_input", {}))
        if state["tool_name"] in {"get_job", "get_customer"}:
            alias = "job_id" if state["tool_name"] == "get_job" else "customer_id"
            if "id" not in tool_input and alias in tool_input:
                tool_input["id"] = tool_input.pop(alias)
            # Coerce int IDs to str (LLM sometimes returns bare integers)
            if "id" in tool_input and not isinstance(tool_input["id"], str):
                tool_input["id"] = str(tool_input["id"])
        elif state["tool_name"] in {"get_open_invoices", "get_all_invoices"}:
            if "customer_id" not in tool_input and "id" in tool_input:
                tool_input["customer_id"] = tool_input.pop("id")
            # Coerce int IDs to str
            if "customer_id" in tool_input and not isinstance(
                tool_input["customer_id"], str
            ):
                tool_input["customer_id"] = str(tool_input["customer_id"])
        result = tool.invoke(tool_input)
        if not isinstance(result, dict):
            raise TypeError("Agent tools must return dictionary results")
        return {**state, "tool_result": result}

    @traceable(name="rag_node")
    def _rag_execution_node(self, state: AgentState) -> AgentState:
        rag_instance = self._rag_node or RAGNode()
        result = rag_instance.run(state["ticket_text"])
        sources = [
            str(doc.metadata["source"])
            for doc in result.retrieved_chunks
            if "source" in doc.metadata
        ]
        return {
            **state,
            "rag_result": result,
            "final_response": result.final_response,
            "tool_result": {"sources": sources} if sources else {},
        }

    @staticmethod
    @traceable(name="handoff_node")
    def _handoff_node(state: AgentState) -> AgentState:
        reason = state.get("handoff_reason") or "Human support is required."
        return {
            **state,
            "final_response": (
                f"I’m handing this ticket to human support. Reason: {reason}"
            ),
        }

    @traceable(name="final_node")
    def _final_node(self, state: AgentState) -> AgentState:
        if state["route"] in {"respond", "rag"}:
            return {
                **state,
                "final_response": state.get("final_response")
                or state.get("response", ""),
            }
        if state["route"] == "handoff":
            return state
        result = json.dumps(state.get("tool_result", {}))
        answer = self._client().generate(
            "Answer the customer using only the supplied database tool result.",
            f"Ticket: {state['ticket_text']}\nTool result: {result}",
        )
        return {**state, "final_response": answer}


def build_helpdesk_graph(
    decision_node: Any,
    tool_node: Any,
    handoff_node: Any,
    rag_node: Any,
    final_node: Any,
) -> Any:
    """Build a graph from independently testable node callables."""
    graph = StateGraph(AgentState)
    graph.add_node("decide", decision_node)
    graph.add_node("tool", tool_node)
    graph.add_node("human_handoff", handoff_node)
    graph.add_node("rag", rag_node)
    graph.add_node("final", final_node)

    graph.add_edge(START, "decide")
    graph.add_conditional_edges(
        "decide",
        lambda state: state["route"],
        {
            "tool": "tool",
            "handoff": "human_handoff",
            "rag": "rag",
            "respond": "final",
        },
    )
    graph.add_edge("tool", "final")
    graph.add_edge("human_handoff", "final")
    graph.add_edge("rag", "final")
    graph.add_edge("final", END)
    return graph.compile()
