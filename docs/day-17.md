# Day 17: LangGraph agents

## Implemented

- Added a typed shared `AgentState` for ticket text, routing decisions, tool
  results, handoff information, and final output.
- Added a LangGraph `StateGraph` with decision, tool, human-handoff, and final
  response nodes.
- Reused the Day 16 repository-backed `StructuredTool` implementations.
- Added a Pydantic-validated LLM decision contract for `tool`, `handoff`, and
  `respond` routes.
- Added LangGraph and graph-route tests with mocked LLM responses.

## What worked

The direct-response route reaches the final node, the database route executes
an existing job tool and gives its result to the LLM, and the human-handoff
route produces a handoff message without invoking tools or a final LLM call.

## What could be improved

The current graph intentionally supports one tool step per ticket. A later
iteration could add a bounded tool loop, richer multi-tool conversations,
checkpointing, streaming, and a dedicated human-review queue. Provider-specific
decision schemas could also replace the generic JSON decision request.

## Verification

All graph tests use mocked LLM calls and an in-memory SQLite database. No live
provider request is required for the test suite.
