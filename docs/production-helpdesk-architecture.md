# Production Helpdesk Operations Architecture

## Current Architecture

The project already contains a working helpdesk AI prototype:

- FastAPI routes in `src/api/` expose health, ticket classification, ticket context,
  async processing, and chat endpoints.
- `src/agent/graph.py` uses LangGraph to route requests to database tools, RAG,
  direct responses, or human handoff.
- `src/tools/` contains typed, repository-backed read tools for customers, jobs,
  and invoices.
- `src/db/data_layer.py` combines SQLite relational records with JSON transcript
  storage from `src/clients/nosql_client.py`.
- `src/rag/` and `src/agent/rag_node.py` support local knowledge-base retrieval
  and grounding checks.
- `src/ml/`, `src/llm/`, and `src/services/ticket_classifier.py` provide ticket
  classification through local ML and structured LLM extraction.

## Existing Capabilities

- Seeded SQLite records for customers, jobs, invoices, and tickets.
- Ticket classification and escalation rules.
- Customer/job/invoice lookup tools.
- RAG over helpdesk knowledge-base documents.
- FastAPI service and Celery task entry points.
- Evaluation fixtures and regression tests for the current agent pipeline.

## Missing Components

- Authenticated customer identity propagation for every operation.
- Write-side business services for jobs, tickets, invoices, approvals, and
  escalations.
- Human approval state machine for AI-generated email.
- Structured engineer and engineer-skill records.
- Ownership checks before customer-owned records are returned or mutated.
- Audit log coverage for important state changes.
- Email receiver/parser/sender interfaces and real ingestion workflow.
- Invoice line items and richer billing business rules.

## Target Architecture

```text
FastAPI / Workers / Email Receiver
        |
        v
Agent decision layer
        |
        v
Validated tool facade
        |
        v
Authorization-aware service layer
        |
        v
Repository/data layer
        |
        v
SQLite / JSON transcript storage / vector index
```

The LLM remains an untrusted decision component. It may classify, summarize, or
request a tool, but authorization, ownership, business validation, approval
gates, and persistence are enforced below the agent layer.

## Database And Model Changes

Phase 1 extends the existing schema instead of replacing it:

- `engineers` and `engineer_skills` for structured engineer eligibility.
- `ticket_messages` for email/conversation history.
- `email_drafts` for `draft -> human_review -> approved/rejected -> sent`.
- `escalations` for human support queues.
- `audit_log` for customer registration, jobs, assignment, drafts, approvals,
  sending, and later agent/tool decisions.
- Existing `customers`, `jobs`, `tickets`, and `invoices` gain production fields
  while retaining compatibility with the current seed data and tests.

## Implementation Phases

1. Foundation and guardrails
   Add schema tables, ownership-aware services, engineer eligibility, email draft
   approval gates, and audit logging.

2. Email ingestion
   Add `EmailReceiver`, `EmailParser`, and `EmailSender` interfaces. Convert
   inbound messages into ticket messages and drafts without directly sending AI
   responses.

3. Ticket and escalation workflow
   Implement create/update ticket services, conversation threading, explicit
   escalation records, and support queue APIs.

4. Invoice workflow
   Add invoice line items, draft/issue/void transitions, ownership checks, and
   invoice tools.

5. Agent tools
   Expose service-backed tools for safe job, ticket, engineer, invoice, email,
   knowledge-base, and escalation actions.

6. End-to-end workflow hardening
   Add mocked LLM/email tests for complete customer email -> ticket -> job ->
   assignment -> invoice -> draft -> approval -> send flows, including prompt
   injection and tool failure cases.
