# LangChain ticket-classification chain

Day 15 adds a LangChain equivalent of the Day 14 classification step while
leaving database persistence in the Day 14 service. `TicketClassificationChain`
uses the existing Day 12 prompt files and Day 11 `LLMClient`; it does not add an
agent, tools, RAG, or LangGraph.

```text
Ticket
  ↓
PromptTemplate
  ↓
LLM
  ↓
OutputParser
  ↓
TicketClassification
```

`PromptTemplate` combines the selected prompt, ticket text, and the format
instructions supplied by LangChain's `PydanticOutputParser`. A `RunnableLambda`
adapts `LLMClient.generate_json` into the runnable chain. The parser receives
the JSON response and validates it against the existing Day 13
`TicketClassification` schema.

Use the chain when only classification is needed:

```python
from chains.ticket_chain import TicketClassificationChain

classification = TicketClassificationChain(prompt_version="v3").invoke(
    "My air conditioner stopped working and I need a technician today."
)
```

For persistence, pass the resulting validated object to the existing Day 14
repository/service flow. Invalid JSON or schema-invalid values produce a
LangChain parser exception and are not persisted by this chain.

## Live LangChain smoke test

With a configured `.env`, run:

```powershell
@'
from chains.ticket_chain import TicketClassificationChain

result = TicketClassificationChain(prompt_version="v1").invoke(
    "My air conditioner stopped cooling; I need a technician today."
)
print(result.model_dump_json(indent=2))
'@ | .\.venv\Scripts\python.exe
```

For an offline test, run `pytest tests/test_ticket_chain.py`.
