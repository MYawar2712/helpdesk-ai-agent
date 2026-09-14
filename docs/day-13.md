# Structured LLM outputs

LLM text can be incomplete, prose instead of data, or contain values the helpdesk
workflow cannot safely route. Validation makes the model's response dependable
enough for downstream application code.

`TicketClassification` in `llm.structured_extract` is a Pydantic model defining
the only accepted result: an allowed category and priority, confidence between
0.0 and 1.0, and a real JSON boolean for `needs_escalation`. Pydantic parses the
JSON object returned by `LLMClient.generate_json` and validates it against those
rules, including rejecting unexpected fields.

```text
Ticket
  ↓
Prompt
  ↓
LLM
  ↓
JSON
  ↓
Pydantic
  ↓
Valid?
 ├── Yes → TicketClassification
 └── No  → Retry
```

`extract_ticket_classification(ticket_text, prompt)` adds explicit JSON-only
instructions to the supplied classification prompt, calls the Day 11
`LLMClient`, and returns a validated `TicketClassification`. Invalid JSON and
Pydantic validation failures cause a correction retry; the retry asks only for a
schema-compliant JSON result and does not expose internal error details to an end
user. `max_retries` controls additional attempts (default `2`, so at most three
requests). If all attempts fail, `StructuredOutputError` is raised rather than
returning untrusted data.

## Live JSON smoke test

With `LLM_API_KEY` configured in `.env`, run this from the repository root:

```powershell
@'
from pathlib import Path
from llm.structured_extract import extract_ticket_classification

prompt = Path("prompts/ticket_classifier/v1.md").read_text(encoding="utf-8")
result = extract_ticket_classification(
    "My air conditioner stopped cooling; I need a technician today.", prompt
)
print(result.model_dump_json(indent=2))
'@ | .\.venv\Scripts\python.exe
```

For an offline test, run `pytest tests/test_structured_extract.py`.
