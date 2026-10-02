"""Day 7 multi-agent helpdesk architecture.

Public surface:

- :class:`~agents.orchestrator.MultiAgentHelpdesk` — the facade the chat
  endpoint invokes.
- :class:`~agents.context.AgentContext` — server-derived identity handed to
  every tool.
- :class:`~agents.tools.ToolRegistry` — the only path from an agent to data.
"""

from agents.context import (
    AgentAuthorizationError,
    AgentContext,
    AgentToolError,
)
from agents.decisions import (
    AgentDestination,
    AgentResult,
    RoutingDecision,
    TicketAction,
)
from agents.orchestrator import MultiAgentHelpdesk
from agents.state import MultiAgentState
from agents.supervisor import SupervisorAgent

__all__ = [
    "AgentAuthorizationError",
    "AgentContext",
    "AgentDestination",
    "AgentResult",
    "AgentToolError",
    "MultiAgentHelpdesk",
    "MultiAgentState",
    "RoutingDecision",
    "SupervisorAgent",
    "TicketAction",
]
