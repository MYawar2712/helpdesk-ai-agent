"""LangGraph agent for helpdesk decisions, tools, and human handoff."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from llm.client import LLMClient


class AgentState(TypedDict, total=False):
    """Shared state passed between every graph node."""

    ticket_text: str
    route: Literal["tool", "handoff", "respond"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_result: dict[str, Any]
    response: str
    handoff_reason: str
    final_response: str


class AgentDecision(BaseModel):
    """Validated decision returned by the LLM decision node."""

    model_config = ConfigDict(extra="forbid", strict=True)

    route: Literal["tool", "handoff", "respond"]
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    response: str | None = None
    handoff_reason: str | None = None


class DecisionClient(Protocol):
    """LLM methods required by the graph."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...

    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class HelpdeskAgent:
    """Compile and invoke the modular helpdesk LangGraph."""

    def __init__(
        self,
        *,
        llm_client: DecisionClient | None = None,
        tools: list[BaseTool] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tools = {tool.name: tool for tool in tools or []}
        self.graph = build_helpdesk_graph(
            self._decision_node, self._tool_node, self._handoff_node, self._final_node
        )

    def invoke(self, ticket_text: str) -> AgentState:
        """Run the graph for one support ticket."""
        if not ticket_text.strip():
            raise ValueError("ticket_text must not be empty")
        return self.graph.invoke({"ticket_text": ticket_text})

    def _client(self) -> DecisionClient:
        return self._llm_client or LLMClient()

    def _decision_node(self, state: AgentState) -> AgentState:
        decision_data = self._client().generate_json(
            """You are a helpdesk routing decision maker. Return JSON only.
Choose route 'tool' when database information is needed, 'handoff' when a human
must handle the ticket, or 'respond' when no database lookup is needed.
For tool, provide tool_name and tool_input. For handoff, provide handoff_reason.
For respond, provide response. Allowed tools are: get_job, get_customer,
get_open_invoices.""",
            state["ticket_text"],
        )
        # Some compatible models use `tool` as the tool name and omit the
        # explicit route. Normalize that equivalent response before validation.
        if "route" not in decision_data and "tool" in decision_data:
            decision_data = {
                **decision_data,
                "route": "tool",
                "tool_name": decision_data["tool"],
            }
            decision_data.pop("tool", None)
        decision = AgentDecision.model_validate(decision_data)
        if decision.route == "tool" and decision.tool_name not in self._tools:
            raise ValueError(f"Unknown or unavailable tool: {decision.tool_name}")
        return {
            **state,
            "route": decision.route,
            "tool_name": decision.tool_name or "",
            "tool_input": decision.tool_input,
            "response": decision.response or "",
            "handoff_reason": decision.handoff_reason or "",
        }

    def _tool_node(self, state: AgentState) -> AgentState:
        tool = self._tools[state["tool_name"]]
        tool_input = dict(state.get("tool_input", {}))
        if state["tool_name"] in {"get_job", "get_customer"}:
            alias = "job_id" if state["tool_name"] == "get_job" else "customer_id"
            if "id" not in tool_input and alias in tool_input:
                tool_input["id"] = tool_input.pop(alias)
        elif state["tool_name"] == "get_open_invoices":
            if "customer_id" not in tool_input and "id" in tool_input:
                tool_input["customer_id"] = tool_input.pop("id")
        result = tool.invoke(tool_input)
        if not isinstance(result, dict):
            raise TypeError("Agent tools must return dictionary results")
        return {**state, "tool_result": result}

    @staticmethod
    def _handoff_node(state: AgentState) -> AgentState:
        reason = state.get("handoff_reason") or "Human support is required."
        return {
            **state,
            "final_response": (
                f"I’m handing this ticket to human support. Reason: {reason}"
            ),
        }

    def _final_node(self, state: AgentState) -> AgentState:
        if state["route"] == "respond":
            return {**state, "final_response": state.get("response", "")}
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
    final_node: Any,
) -> Any:
    """Build a graph from independently testable node callables."""

    graph = StateGraph(AgentState)
    graph.add_node("decide", decision_node)
    graph.add_node("tool", tool_node)
    graph.add_node("human_handoff", handoff_node)
    graph.add_node("final", final_node)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges(
        "decide",
        lambda state: state["route"],
        {"tool": "tool", "handoff": "human_handoff", "respond": "final"},
    )
    graph.add_edge("tool", "final")
    graph.add_edge("human_handoff", "final")
    graph.add_edge("final", END)
    return graph.compile()
