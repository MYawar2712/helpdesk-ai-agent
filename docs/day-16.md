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

## Live tool-calling smoke test

With a tool-capable model configured in `.env`, run:

```powershell
@'
import sqlite3
from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from llm.client import LLMClient
from tools.get_customer import create_get_customer_tool
from tools.get_job import create_get_job_tool
from tools.get_open_invoices import create_get_open_invoices_tool
from tools.tool_calling import ToolCallingAssistant

connection = sqlite3.connect(":memory:")
seed_database(connection)
repository = HelpdeskDataRepository(connection, NoSQLClient(sqlite3.connect(":memory:")))
assistant = ToolCallingAssistant(LLMClient(), [
    create_get_job_tool(repository),
    create_get_customer_tool(repository),
    create_get_open_invoices_tool(repository),
])
print(assistant.answer("What is the status of job job-1?"))
'@ | .\.venv\Scripts\python.exe
```

This uses an in-memory database and does not change the local database file.
