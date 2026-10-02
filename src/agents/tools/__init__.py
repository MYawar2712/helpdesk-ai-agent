"""Day 7 agent tool registry.

``build_tool_registry`` assembles every specialized agent's tools into a single
:class:`~agents.tools.base.ToolRegistry`, which is the only path from an agent
to business data. Identity is injected from the server-side
:class:`~agents.context.AgentContext`, never from model output.
"""

from agents.tools.base import (
    HUMAN,
    INVOICE,
    JOB,
    SUPERVISOR,
    SUPPORT,
    TRIAGE,
    AgentTool,
    ToolRegistry,
)
from agents.tools.invoice_tools import register_invoice_tools
from agents.tools.job_tools import register_job_tools
from agents.tools.support_tools import (
    KeywordKnowledgeRetriever,
    KnowledgeRetriever,
    register_support_tools,
)
from agents.tools.ticket_tools import register_ticket_tools

__all__ = [
    "AgentTool",
    "HUMAN",
    "INVOICE",
    "JOB",
    "KeywordKnowledgeRetriever",
    "KnowledgeRetriever",
    "SUPERVISOR",
    "SUPPORT",
    "TRIAGE",
    "ToolRegistry",
    "build_tool_registry",
    "register_invoice_tools",
    "register_job_tools",
    "register_support_tools",
    "register_ticket_tools",
]


def build_tool_registry(
    repository: object,
    *,
    retriever: KnowledgeRetriever | None = None,
) -> ToolRegistry:
    """Build the registry of all Day 7 tools.

    Args:
        repository: A ``HelpdeskDataRepository`` used for every business tool.
        retriever: Knowledge retriever for the Support Agent. Defaults to the
            deterministic keyword retriever; Day 8 supplies the vector-backed one.
    """

    registry = ToolRegistry()
    knowledge = retriever or KeywordKnowledgeRetriever()
    register_support_tools(registry, knowledge)
    register_job_tools(registry, repository)  # type: ignore[arg-type]
    register_invoice_tools(registry, repository)  # type: ignore[arg-type]
    register_ticket_tools(registry, repository)  # type: ignore[arg-type]
    return registry
