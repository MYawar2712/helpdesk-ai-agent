# Day 14: Week 2 summary

## Built

- Integrated the Day 11 LLM client, Day 12 prompts, and Day 13 structured extraction
- Added `TicketClassifier` with configurable `v1`, `v2`, and `v3` prompt selection
- Validated classifications with the Pydantic `TicketClassification` model
- Added bounded retry behavior for invalid JSON and schema-invalid responses
- Persisted validated category, priority, confidence, and escalation values to SQLite
- Added database migration support for the new classification fields
- Added service, persistence, failure-path, and end-to-end tests

## Architecture

```text
Raw Ticket
    ↓
Prompt Loader
    ↓
LLMClient
    ↓
Structured JSON
    ↓
Pydantic Validation
    ↓
TicketClassification
    ↓
HelpdeskDataRepository
    ↓
SQLite
```

The classifier service coordinates the workflow while keeping prompt loading,
LLM extraction, validation, and database access as separate responsibilities.
Invalid or exhausted LLM responses are raised and never persisted.

## Tests and verification

- Day 14 tests cover successful classification, billing and scheduling examples,
  prompt selection, invalid output, persistence, database failures, and the
  complete mocked pipeline.
- Full suite result: **81 tests passed**
- Ruff checks passed for the project sources and tests.
- Tests use mocked LLM responses and do not require a live API.

## Challenges and decisions

The existing `tickets` table already contained category and priority, so only
confidence and escalation fields were added. The database initializer performs
a minimal migration for existing SQLite databases. Persistence happens only
after Pydantic validation succeeds.

## Week 3 focus

Rebuild the classifier with LangChain prompt/runnable composition, then add
typed database tools and LLM function calling while keeping persistence and
provider access isolated behind existing services.
