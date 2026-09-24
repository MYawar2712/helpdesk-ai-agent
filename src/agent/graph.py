"""LangGraph agent for helpdesk decisions, tools, RAG, and human handoff."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.rag_node import RAGNode
from agent.tracing import traceable
from clients.nosql_client import NoSQLClient
from db.conversation_repository import ConversationMessage, ConversationRepository
from db.data_layer import HelpdeskDataRepository
from guardrails.checks import (
    apply_output_guardrails,
    build_refusal_state,
    check_input,
    check_output,
)
from llm.client import LLMClient
from models import TicketIntent
from tools.cancel_job import create_cancel_job_tool
from tools.classify_intent import classify_intent
from tools.get_all_invoices import create_get_all_invoices_tool
from tools.get_customer import create_get_customer_tool
from tools.get_job import create_get_job_tool
from tools.get_open_invoices import create_get_open_invoices_tool
from tools.schedule_job import create_schedule_job_tool
from tools.update_job_status import create_update_job_status_tool

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Maximum number of prior conversation messages passed to the LLM.  Kept
#: small enough to avoid prompt bloat while still providing useful context.
#: Override via the ``CONVERSATION_HISTORY_LIMIT`` environment variable.
_DEFAULT_HISTORY_LIMIT: int = 20


def _history_limit() -> int:
    """Return the configured conversation history limit."""
    try:
        return max(
            1, int(os.environ.get("CONVERSATION_HISTORY_LIMIT", _DEFAULT_HISTORY_LIMIT))
        )
    except (TypeError, ValueError):
        return _DEFAULT_HISTORY_LIMIT


class AgentState(TypedDict, total=False):
    """Shared state passed between every graph node.

    Conversation-memory fields
    --------------------------
    thread_id:
        The persistent email-thread identifier (= email provider thread ID
        when available, otherwise a generated UUID).  Kept separate from
        ``ticket_id`` which is a helpdesk-issue identifier.
    conversation_history:
        Ordered list of prior :class:`~db.conversation_repository.ConversationMessage`
        objects loaded before the graph runs.  The decision node uses these to
        build context-aware prompts.
    """

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
    intent: str
    ticket_id: str
    customer_id: str
    # ── Conversation memory ──────────────────────────────────────────────
    thread_id: str
    conversation_history: list[ConversationMessage]


class AgentDecision(BaseModel):
    """Validated decision returned by the LLM decision node."""

    model_config = ConfigDict(extra="ignore")

    route: Literal["tool", "handoff", "respond", "rag"]
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    response: str | None = None
    handoff_reason: str | None = None
    intent: str | None = None

    @field_validator("tool_input", mode="before")
    @classmethod
    def _validate_tool_input(cls, v: Any) -> dict[str, Any]:
        if v is None or not isinstance(v, dict):
            return {}
        return v


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
            create_cancel_job_tool(repo),
            create_update_job_status_tool(repo),
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
        conversation_repo: ConversationRepository | None = None,
    ) -> None:
        self._llm_client = llm_client
        active_tools = tools if tools is not None else create_default_tools()
        self._tools = {tool.name: tool for tool in active_tools}
        self._rag_node = rag_node
        self._conv_repo = conversation_repo
        self.graph = build_helpdesk_graph(
            self._decision_node,
            self._tool_node,
            self._handoff_node,
            self._rag_execution_node,
            self._final_node,
        )

    @traceable(name="helpdesk_agent")
    def invoke(
        self,
        ticket_text: str,
        *,
        email_thread_id: str | None = None,
        email_message_id: str | None = None,
        customer_id: str | None = None,
        sender_email: str = "",
    ) -> AgentState:
        """Run input guardrails, the existing graph, then output guardrails.

        Conversation memory lifecycle
        -----------------------------
        1. Extract (or generate) the thread ID from *email_thread_id*.
        2. Load the existing thread and its recent messages, or create a new
           thread when none exists.
        3. Save the inbound customer message (idempotent via *email_message_id*).
        4. Inject history into the initial graph state.
        5. After the graph completes, save the agent response to the same thread.

        Parameters
        ----------
        ticket_text:
            The raw customer message text.
        email_thread_id:
            Provider-level thread identifier (e.g. Gmail thread ID).  When
            supplied the agent continues an existing conversation rather than
            starting a new one.
        email_message_id:
            Provider-level message identifier used for idempotency.  Receiving
            the same message twice will not create a duplicate.
        customer_id:
            The customer's identifier.  Extracted from *ticket_text* when
            omitted.
        sender_email:
            The customer's email address (stored in the message record).
        """
        if not ticket_text.strip():
            raise ValueError("ticket_text must not be empty")
        inbound = check_input(ticket_text)
        if not inbound.allowed:
            return build_refusal_state(
                redacted_text=inbound.redacted_text,
                reason=inbound.reason,
                category=inbound.category,
                pii_types=inbound.pii_types,
            )

        # ------------------------------------------------------------------
        # Conversation-memory: resolve thread and load history
        # ------------------------------------------------------------------
        thread_id: str | None = None
        history: list[ConversationMessage] = []
        resolved_customer_id = customer_id or _extract_customer_id(
            inbound.redacted_text
        )

        if self._conv_repo is not None and resolved_customer_id:
            thread_id, history = self._load_or_create_thread(
                email_thread_id=email_thread_id,
                customer_id=resolved_customer_id,
            )
            # Persist the inbound customer message (idempotent)
            self._conv_repo.add_message(
                thread_id=thread_id,
                customer_id=resolved_customer_id,
                sender_type="customer",
                content=inbound.redacted_text,
                sender_email=sender_email,
                email_message_id=email_message_id,
            )

        # ------------------------------------------------------------------
        # Build initial state and run the graph
        # ------------------------------------------------------------------
        initial_state: AgentState = {"ticket_text": inbound.redacted_text}
        if thread_id:
            initial_state["thread_id"] = thread_id
        if resolved_customer_id:
            initial_state["customer_id"] = resolved_customer_id
        if history:
            initial_state["conversation_history"] = history

        state = self.graph.invoke(initial_state)

        # ------------------------------------------------------------------
        # Conversation-memory: persist the agent response
        # ------------------------------------------------------------------
        if self._conv_repo is not None and thread_id and resolved_customer_id:
            agent_response = state.get("final_response") or state.get("response") or ""
            if agent_response:
                self._conv_repo.add_message(
                    thread_id=thread_id,
                    customer_id=resolved_customer_id,
                    sender_type="agent",
                    content=agent_response,
                )

        outbound = check_output(
            state.get("final_response") or state.get("response") or "",
            input_text=inbound.redacted_text,
            state=state,
        )
        return apply_output_guardrails(state, outbound)

    def _load_or_create_thread(
        self,
        *,
        email_thread_id: str | None,
        customer_id: str,
    ) -> tuple[str, list[ConversationMessage]]:
        """Return (thread_id, recent_messages) for a customer.

        Looks up an existing thread by *email_thread_id* (validating that it
        belongs to *customer_id*), or creates a fresh one when no match is
        found.
        """
        repo = self._conv_repo
        assert repo is not None  # guarded by caller

        limit = _history_limit()

        if email_thread_id:
            thread = repo.get_thread(email_thread_id)
            if thread is not None:
                if thread.customer_id == customer_id:
                    msgs = repo.get_recent_messages(
                        thread.thread_id, limit=limit, customer_id=customer_id
                    )
                    return thread.thread_id, msgs
                else:
                    # Security violation: thread exists but belongs to another customer.
                    # Create a fresh thread to keep customer data isolated.
                    new_thread = repo.create_thread(customer_id=customer_id)
                    return new_thread.thread_id, []

        # No existing thread – create one using the provider ID as the key
        # when available so future replies are matched automatically.
        new_thread = repo.create_thread(
            customer_id=customer_id,
            thread_id=email_thread_id,  # None → UUID generated inside
        )
        return new_thread.thread_id, []

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

        ticket_text = state["ticket_text"]
        customer_match = re.search(r"Customer ID:\s*([^\n]+)", ticket_text)
        ticket_match = re.search(r"Ticket ID:\s*([^\n]+)", ticket_text)
        customer_id = state.get("customer_id") or (
            customer_match.group(1).strip() if customer_match else ""
        )
        ticket_id = state.get("ticket_id") or (
            ticket_match.group(1).strip() if ticket_match else ""
        )
        classified_intent = classify_intent(ticket_text)
        intent = classified_intent.value

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
        lowered = ticket_text.lower()
        if any(k in lowered for k in dispute_keywords):
            return {
                **state,
                "predicted_category": category,
                "predicted_priority": priority,
                "confidence_score": confidence,
                "intent": TicketIntent.BILLING_INQUIRY.value,
                "customer_id": customer_id,
                "ticket_id": ticket_id,
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

        short_circuit = _intent_short_circuit(
            classified_intent, customer_id, ticket_text
        )
        if short_circuit is not None:
            tool_name = short_circuit.get("tool_name") or ""
            if short_circuit.get("route") != "tool" or tool_name in self._tools:
                return {
                    **state,
                    "predicted_category": category,
                    "predicted_priority": priority,
                    "confidence_score": confidence,
                    "intent": intent,
                    "customer_id": customer_id,
                    "ticket_id": ticket_id,
                    **short_circuit,
                }

        # Build the conversation-history section of the prompt when prior
        # messages are available.  Only the most-recent messages are injected
        # (the limit was already applied when loading history).
        history: list[ConversationMessage] = state.get("conversation_history") or []
        history_section = ""
        if history:
            lines = []
            for msg in history:
                role = msg.sender_type.upper()
                lines.append(f"[{role}]: {msg.content}")
            history_section = (
                "\n\nPrevious conversation history (oldest first):\n"
                + "\n".join(lines)
                + "\n\nUse this history to understand references in the current "
                "message (e.g. a customer replying with a job ID is answering a "
                "previous agent request). Do NOT start a new unrelated conversation "
                "when the message is clearly a follow-up reply.\n"
            )

        decision_prompt = f"""You are a helpdesk routing decision maker.
Return JSON only.
ML Classification Context: Category={category}, Priority={priority},
Confidence={confidence:.2f}
Pre-classified intent: {intent}{history_section}
Route this intent as follows:
- CANCEL_JOB → route 'tool', tool_name 'cancel_job' with customer_id and optional job_id
- JOB_STATUS → route 'tool', tool_name 'get_job' when one specific job is requested;
  use tool_name 'get_customer' with the customer ID when previous, past, or all jobs
  are requested
- RESCHEDULE_JOB or MODIFY_JOB → route 'tool', tool_name 'update_job_status'
- NEW_SERVICE_REQUEST → route 'respond' (job is created later by the draft/email flow;
  do NOT create a job yourself)
- GENERAL_INQUIRY, BILLING_INQUIRY, TECHNICAL_SUPPORT → route 'rag' or 'respond'
- HUMAN_ESCALATION, COMPLAINT → route 'handoff'
Choose route 'tool' when database information (get_job, get_customer,
get_open_invoices, get_all_invoices, cancel_job, update_job_status) is needed.
Use get_open_invoices for unpaid or overdue invoices. Use get_all_invoices when all
paid and unpaid invoices are requested. Choose 'rag' when knowledge-base, policy,
warranty, or technical troubleshooting information is needed. Choose 'respond' when
drafting a customer reply or handling new service requests.
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
get_open_invoices, get_all_invoices, schedule_job, cancel_job, update_job_status."""

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
            "intent": decision.intent or intent,
            "customer_id": customer_id,
            "ticket_id": ticket_id,
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

        # Extract requesting customer_id from ticket_text context
        match = re.search(r"Customer ID:\s*([^\n]+)", state.get("ticket_text", ""))
        requesting_customer_id = match.group(1).strip() if match else None

        if state["tool_name"] in {"get_job", "get_customer"}:
            alias = "job_id" if state["tool_name"] == "get_job" else "customer_id"
            if "id" not in tool_input and alias in tool_input:
                tool_input["id"] = tool_input.pop(alias)
            # Coerce int IDs to str (LLM sometimes returns bare integers)
            if "id" in tool_input and not isinstance(tool_input["id"], str):
                tool_input["id"] = str(tool_input["id"])

            # A customer-level job-history request is sometimes misclassified as
            # get_job by the LLM.  get_job requires an individual id, while
            # get_customer is the tool that returns the customer's complete job
            # history.  Redirect before invoking the typed tool so it cannot
            # raise a missing-id validation error.
            if (
                state["tool_name"] == "get_job"
                and "id" not in tool_input
                and ("customer_id" in tool_input or "customer_id" in state)
                and "get_customer" in self._tools
            ):
                tool = self._tools["get_customer"]
                tool_input = {
                    "id": tool_input.get("customer_id") or state["customer_id"]
                }
        elif state["tool_name"] in {"get_open_invoices", "get_all_invoices"}:
            if "customer_id" not in tool_input and "id" in tool_input:
                tool_input["customer_id"] = tool_input.pop("id")
            # Coerce int IDs to str
            if "customer_id" in tool_input and not isinstance(
                tool_input["customer_id"], str
            ):
                tool_input["customer_id"] = str(tool_input["customer_id"])
        elif state["tool_name"] in {"cancel_job", "update_job_status"}:
            if "customer_id" not in tool_input and requesting_customer_id:
                tool_input["customer_id"] = requesting_customer_id
            if "customer_id" in tool_input and not isinstance(
                tool_input["customer_id"], str
            ):
                tool_input["customer_id"] = str(tool_input["customer_id"])
            if "job_id" in tool_input and not isinstance(tool_input["job_id"], str):
                tool_input["job_id"] = str(tool_input["job_id"])

        # Pre-check: prevent querying another customer's ID explicitly
        target_id = tool_input.get("id") or tool_input.get("customer_id")
        if (
            requesting_customer_id
            and target_id
            and target_id.startswith("customer-")
            and target_id != requesting_customer_id
        ):
            _privacy_err = (
                "Privacy policy restriction: For privacy and "
                "security reasons, I cannot provide job details "
                "or information belonging to another customer."
            )
            return {
                **state,
                "tool_result": {
                    "found": False,
                    "error": _privacy_err,
                    "forbidden": True,
                },
            }

        result = tool.invoke(tool_input)

        if (
            state["tool_name"] == "get_job"
            and isinstance(result, dict)
            and not result.get("found")
            and "customer_id" in tool_input
        ):
            cand_cust = tool_input["customer_id"]
            if not requesting_customer_id or cand_cust == requesting_customer_id:
                fallback_res = tool.invoke({"id": cand_cust})
                if isinstance(fallback_res, dict) and fallback_res.get("found"):
                    result = fallback_res

        # Post-check: verify returned resource belongs to requesting_customer_id
        if requesting_customer_id and isinstance(result, dict) and result.get("found"):
            resource = result.get("job") or result.get("customer")
            if isinstance(resource, dict):
                res_cust_id = resource.get("customer_id") or resource.get("id")
                if res_cust_id and res_cust_id != requesting_customer_id:
                    _post_privacy_err = (
                        "Privacy policy restriction: For privacy and "
                        "security reasons, I cannot provide job details "
                        "or information belonging to another customer."
                    )
                    result = {
                        "found": False,
                        "error": _post_privacy_err,
                        "forbidden": True,
                    }

        if isinstance(result, str):
            result = {"result": result}
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
            "Answer the customer using only the supplied database tool result. "
            "If requires_job_id is true, clearly ask which specific job ID they "
            "want to cancel and confirm that no cancellation was made. If a job "
            "was created and a job ID is present, include that job ID in the reply.",
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


def _extract_job_id(text: str) -> str | None:
    match = re.search(
        r"\b(job-[a-f0-9-]+|job-\d+)\b",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _extract_customer_id(text: str) -> str | None:
    """Extract a customer ID embedded in the ticket text, or return None."""
    m = re.search(r"Customer ID:\s*([^\n]+)", text)
    return m.group(1).strip() if m else None


def _intent_short_circuit(
    intent: TicketIntent, customer_id: str, ticket_text: str
) -> dict[str, Any] | None:
    """Skip the LLM for obvious keyword-classified intents."""
    if intent is TicketIntent.CANCEL_JOB and customer_id:
        tool_input: dict[str, Any] = {"customer_id": customer_id}
        job_id = _extract_job_id(ticket_text)
        if job_id:
            tool_input["job_id"] = job_id
        return {
            "route": "tool",
            "tool_name": "cancel_job",
            "tool_input": tool_input,
            "response": "",
            "handoff_reason": "",
        }
    if intent is TicketIntent.JOB_STATUS:
        job_id = _extract_job_id(ticket_text)
        if job_id:
            return {
                "route": "tool",
                "tool_name": "get_job",
                "tool_input": {"id": job_id},
                "response": "",
                "handoff_reason": "",
            }
    if intent in {TicketIntent.HUMAN_ESCALATION, TicketIntent.COMPLAINT}:
        reason = (
            "Customer requested a human agent"
            if intent is TicketIntent.HUMAN_ESCALATION
            else "Customer complaint requires human review"
        )
        return {
            "route": "handoff",
            "tool_name": "",
            "tool_input": {},
            "response": f"I'm handing this ticket to human support. Reason: {reason}",
            "handoff_reason": reason,
        }
    return None
