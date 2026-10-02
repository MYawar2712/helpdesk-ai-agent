"""Shared LangGraph state for the Day 7 multi-agent helpdesk workflow.

The state carries *only* the small amount of context each agent needs. Bulk
database records are never placed in the graph state; agents read them through
authorized tools instead.

``conversation_id`` remains the canonical identifier and is used verbatim as the
LangGraph ``thread_id`` (see :mod:`agents.orchestrator`).
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

#: Upper bound on the number of messages carried in graph state. The business
#: ``messages`` table remains the durable transcript; this is prompt context only.
MAX_STATE_MESSAGES = 40


def merge_messages(
    left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Append new messages to the conversation, bounded by ``MAX_STATE_MESSAGES``.

    LangGraph uses this as a channel reducer, so it runs on every node that
    returns ``messages``. Bounding the list here keeps checkpoint size and prompt
    length stable across long conversations.
    """

    merged = [*(left or []), *(right or [])]
    return merged[-MAX_STATE_MESSAGES:]


MessagesChannel = Annotated[list[dict[str, Any]], merge_messages]


class MultiAgentState(TypedDict, total=False):
    """State shared by the supervisor, triage, and specialized agents.

    Identity fields (``tenant_id``/``customer_id``/``conversation_id``) are set
    once by the trusted API layer from the authenticated session. They are never
    supplied by, or inferred from, model output.
    """

    # ── Identity / tenancy (server-derived, never model-derived) ──────────
    conversation_id: str
    tenant_id: str | None
    customer_id: str
    customer_email: str

    # ── Turn input ───────────────────────────────────────────────────────
    user_message: str
    messages: MessagesChannel

    # ── Triage output ────────────────────────────────────────────────────
    intent: str
    category: str
    priority: str
    destination: str
    routing_reasoning: str | None
    requires_human: bool
    human_reason: str | None

    # ── Entities resolved during the workflow ────────────────────────────
    ticket_id: str | None
    ticket_action: str
    job_id: str | None
    invoice_id: str | None

    # ── Specialist output ────────────────────────────────────────────────
    agent_result: dict[str, Any] | None
    tool_calls: list[dict[str, Any]]
    #: Day 9: structured action awaiting an approval decision.
    proposed_action: dict[str, Any] | None
    #: Day 9: the tenant configuration used for this turn, so the approval gate
    #: does not re-read it.
    agent_config: Any | None

    # ── Supervisor output ────────────────────────────────────────────────
    final_response: str
    handled_by: str

    # ── Loop control ─────────────────────────────────────────────────────
    iteration: int
    max_iterations: int
    visited_agents: list[str]
    #: Set once the human handover agent has produced its summary. Prevents the
    #: ``supervisor -> human -> supervisor`` cycle from repeating forever.
    human_handover_done: bool
