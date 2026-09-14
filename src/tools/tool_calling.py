"""A bounded provider tool-calling loop for helpdesk database tools."""

from __future__ import annotations

import json
from typing import Any, Protocol

from langchain_core.tools import BaseTool


class ToolCallingClient(Protocol):
    """Minimal provider interface required for a tool-calling conversation."""

    def generate_with_tools(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Any: ...


class ToolCallingAssistant:
    """Let an LLM select one database tool and answer using its result."""

    def __init__(self, llm_client: ToolCallingClient, tools: list[BaseTool]) -> None:
        self.llm_client = llm_client
        self.tools = {tool.name: tool for tool in tools}

    def answer(self, question: str) -> str:
        """Run one tool-selection round followed by a final LLM response."""
        if not question.strip():
            raise ValueError("question must not be empty")
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": "Use database tools when needed. Do not invent records.",
            },
            {"role": "user", "content": question},
        ]
        definitions = [self._tool_definition(tool) for tool in self.tools.values()]
        response = self.llm_client.generate_with_tools(messages, definitions)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return self._content(message)

        messages.append(self._assistant_message(message))
        for tool_call in tool_calls:
            name = tool_call.function.name
            tool = self.tools.get(name)
            if tool is None:
                raise ValueError(f"LLM requested an unknown tool: {name}")
            arguments = json.loads(tool_call.function.arguments)
            result = tool.invoke(arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

        final_response = self.llm_client.generate_with_tools(messages, definitions)
        return self._content(final_response.choices[0].message)

    @staticmethod
    def _tool_definition(tool: BaseTool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_schema.model_json_schema(),
            },
        }

    @staticmethod
    def _assistant_message(message: Any) -> dict[str, Any]:
        tool_calls = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": tool_calls,
        }

    @staticmethod
    def _content(message: Any) -> str:
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned an empty final answer")
        return content
