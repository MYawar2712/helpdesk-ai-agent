# Database tool calling

Function calling lets an LLM request trusted application data instead of
guessing it. Day 16 exposes three typed, read-only database tools:
`get_job(id)`, `get_customer(id)`, and `get_open_invoices(customer_id)`.
They call `HelpdeskDataRepository`, which owns the database queries; tools do
not contain SQL or credentials.

```text
User question
     ↓
    LLM
     ↓
Tool selection
     ↓
Database tool
     ↓
Database
     ↓
Tool result
     ↓
    LLM
     ↓
Final answer
```

`ToolCallingAssistant` sends the available tool schemas to the Day 11
`LLMClient`. If the LLM returns a tool call, the assistant validates and runs
the requested LangChain `StructuredTool`, appends its JSON result as a tool
message, then asks the LLM for a final natural-language answer. The loop is
bounded to one selection round and one final response.

Missing records produce explicit `found: false` results. Empty or invalid IDs
raise `ValueError`; provider and database errors are allowed to propagate.
