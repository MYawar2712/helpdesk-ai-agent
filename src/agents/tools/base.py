"""Validated tool framework for Day 7 specialized agents.

Every tool is declared once with metadata describing which agent may call it and
whether it mutates data. :meth:`ToolRegistry.execute` is the single enforcement
point: it rejects unknown tools, rejects calls from an agent outside the tool's
scope, validates the arguments, and converts failures into structured results
instead of leaking raw database errors.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agents.context import (
    AgentAuthorizationError,
    AgentContext,
    AgentToolError,
)

#: Agent names used for tool scoping.
SUPERVISOR = "supervisor"
TRIAGE = "triage"
SUPPORT = "support"
JOB = "job"
INVOICE = "invoice"
HUMAN = "human"

ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class AgentTool:
    """A single business operation exposed to agents.

    Attributes:
        name: Unique tool name, e.g. ``get_job``.
        description: Human/LLM readable description of the operation.
        handler: Callable invoked as ``handler(ctx, **arguments)``.
        scope: Agents permitted to call this tool.
        mutates: Whether the tool changes persisted data.
        required_arguments: Argument names that must be present.
    """

    name: str
    description: str
    handler: ToolHandler
    scope: frozenset[str]
    mutates: bool = False
    required_arguments: tuple[str, ...] = ()

    def __call__(self, ctx: AgentContext, **arguments: Any) -> dict[str, Any]:
        return self.handler(ctx, **arguments)


@dataclass
class ToolRegistry:
    """Registry that owns tool definitions and enforces access scope."""

    tools: dict[str, AgentTool] = field(default_factory=dict)

    def register(self, tool: AgentTool) -> AgentTool:
        """Add a tool to the registry."""

        if tool.name in self.tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self.tools[tool.name] = tool
        return tool

    def add(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        *,
        scope: frozenset[str] | set[str],
        mutates: bool = False,
        required_arguments: tuple[str, ...] = (),
    ) -> AgentTool:
        """Convenience wrapper around :meth:`register`."""

        return self.register(
            AgentTool(
                name=name,
                description=description,
                handler=handler,
                scope=frozenset(scope),
                mutates=mutates,
                required_arguments=required_arguments,
            )
        )

    def for_agent(self, agent: str) -> list[AgentTool]:
        """Return the tools *agent* is allowed to call."""

        return [tool for tool in self.tools.values() if agent in tool.scope]

    def names_for_agent(self, agent: str) -> list[str]:
        """Return the tool names available to *agent*."""

        return sorted(tool.name for tool in self.for_agent(agent))

    def execute(
        self,
        name: str,
        *,
        ctx: AgentContext,
        calling_agent: str,
        arguments: dict[str, Any] | None = None,
        allowed_tools: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        """Run a tool after validating scope, arguments, and the handler.

        Args:
            name: Registered tool name.
            ctx: Server-derived agent context.
            calling_agent: Agent requesting the call; checked against scope.
            arguments: Domain arguments produced by the agent or LLM.
            allowed_tools: Optional tenant-configured allow-list. This can only
                *narrow* the platform scope: a tool outside it is refused even
                when the platform would otherwise permit it.

        Returns:
            A structured payload. Failures are reported as
            ``{"ok": False, "error": ..., "error_type": ...}`` rather than
            raised, so a single failed tool call cannot abort the workflow.
        """

        arguments = dict(arguments or {})
        tool = self.tools.get(name)
        if tool is None:
            return {
                "ok": False,
                "error": f"unknown tool: {name}",
                "error_type": "unknown_tool",
            }

        if calling_agent not in tool.scope:
            return {
                "ok": False,
                "error": f"tool '{name}' is not available to {calling_agent}",
                "error_type": "forbidden",
            }

        # A tenant allow-list narrows the platform scope; it never grants access.
        if allowed_tools is not None and name not in allowed_tools:
            return {
                "ok": False,
                "error": f"tool '{name}' is not enabled for this tenant",
                "error_type": "forbidden",
            }

        missing = [
            argument
            for argument in tool.required_arguments
            if arguments.get(argument) in (None, "")
        ]
        if missing:
            return {
                "ok": False,
                "error": f"missing required argument(s): {', '.join(missing)}",
                "error_type": "invalid_arguments",
            }

        # Identity arguments are stripped defensively: identity always comes
        # from the context, never from the caller of the tool.
        for reserved in ("customer_id", "tenant_id", "conversation_id"):
            arguments.pop(reserved, None)

        try:
            result = tool(ctx, **arguments)
        except AgentAuthorizationError as error:
            return {
                "ok": False,
                "error": str(error),
                "error_type": "forbidden",
            }
        except AgentToolError as error:
            return {
                "ok": False,
                "error": str(error),
                "error_type": "business_rule",
            }
        except LookupError as error:
            return {
                "ok": False,
                "error": str(error),
                "error_type": "not_found",
            }
        except PermissionError as error:
            return {"ok": False, "error": str(error), "error_type": "forbidden"}
        except Exception as error:  # noqa: BLE001 - never leak internals
            return {
                "ok": False,
                "error": f"tool '{name}' failed: {type(error).__name__}",
                "error_type": "internal",
            }

        if not isinstance(result, dict):
            return {
                "ok": False,
                "error": f"tool '{name}' returned an invalid payload",
                "error_type": "internal",
            }
        return {"ok": True, "tool": name, **result}
