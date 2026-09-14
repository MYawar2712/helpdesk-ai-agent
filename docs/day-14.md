# Ticket classification pipeline

Day 14 combines the prompt, LLM, structured-output, and database components
into one application service.

```text
Raw Ticket
    ↓
Prompt
    ↓
LLM
    ↓
JSON
    ↓
Pydantic
    ↓
Database
```

`TicketClassifier` loads a selected Day 12 prompt (`v1`, `v2`, or `v3`) from
`prompts/ticket_classifier`. It passes the prompt and raw ticket text to the
Day 13 extractor, which uses the Day 11 `LLMClient` JSON mode. The extractor
parses the JSON, validates it as `TicketClassification`, and retries invalid
LLM output before raising an error.

After validation, `classify_and_save(ticket_id, ticket_text)` calls the Week 1
repository to update the ticket's category, priority, confidence, and
`needs_escalation` flag. No database update occurs if extraction or validation
fails. Database errors are allowed to propagate to the caller.

Example:

```text
Input:  My technician was supposed to arrive yesterday but nobody came.
Output: {"category": "scheduling", "priority": "high", "confidence": 0.9,
         "needs_escalation": true}
```

Responsibilities remain separate: prompt files provide instructions,
`LLMClient` performs provider requests, the structured extractor validates and
retries, `TicketClassification` is the trusted result contract, and the
repository persists that trusted data.
