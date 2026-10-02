# helpdesk-ai-agent

A small, typed Python foundation for building and evaluating a helpdesk AI agent.
The project includes a full Week 3 end-to-end AI agent pipeline with LangGraph routing, database function calling, local vector RAG, grounding self-checks, and FastAPI REST endpoints.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pre-commit install
```

Run the checks with:

```powershell
pytest
ruff check .
pre-commit run --all-files
```

---

## Authentication & Authorization Architecture (Day 2 & Day 3)

The Helpdesk AI Agent features multi-tenant data isolation, JWT-based authentication, fine-grained Role-Based Access Control (RBAC), and protection against privilege escalation.

### RBAC Roles & Permissions

- **`PLATFORM_ADMIN`**: Full platform management across all tenants (user CRUD, tenant updates, audit logs).
- **`TENANT_ADMIN`**: Full management within a single tenant boundary. Prevents privilege escalation to `PLATFORM_ADMIN`.
- **`SUPPORT_AGENT`**: Operational support capabilities (ticket triage, job creation/assignment, customer overview).
- **`AI_AGENT`**: Dedicated non-human system role with strict permission boundaries.
- **`CUSTOMER`**: Restricted self-service role. Access limited strictly to owned tickets, jobs, and invoices.

### User Management Endpoints

All user management endpoints strictly derive `tenant_id` from the authenticated administrator and enforce tenant isolation:

- `GET /users` – List users in current tenant (or across tenants for `PLATFORM_ADMIN`).
- `GET /users/{id}` – Get user details by ID.
- `POST /users` – Create a new user (admin-only, prevents privilege escalation).
- `PATCH /users/{id}` – Update user details or role.
- `DELETE /users/{id}` – Delete user account.

### AI Agent Permission Foundation

Subagents and automated tool execution are governed by an explicit agent-to-permission matrix (`src/auth/rbac.py`):
- `JOB_AGENT`: Allowed `job:read`, `job:create`, `job:assign`. Prohibited from `user:delete`, `tenant:update`, `invoice:update`.
- `TICKET_AGENT`: Allowed `ticket:read`, `ticket:create`, `ticket:update`.
- `INQUIRY_AGENT`: Allowed `customer:read`, `invoice:read`.

The package source lives in `src/`, tests in `tests/`, documentation in `docs/`, reusable prompts in `prompts/`, and evaluation material in `eval/`.

---

## Week 3 Architecture: Integrated RAG & Function Calling Agent

The end-to-end Week 3 architecture integrates **FastAPI**, **LangGraph**, **Database Tools**, **Chroma Vector RAG**, **LLM Grounding Self-Check**, and **Structured Pydantic Responses**:

```text
HTTP Request (POST /chat)
       │
       ▼
 FastAPI Router (`api/routes.py`)
       │
       ▼
 LangGraph Agent (`agent/graph.py`)
       ├── Decision Node (Routes: tool | rag | respond | handoff)
       │
       ├── Tool Calling Node (`get_job`, `get_customer`, `get_open_invoices`)
       │
       └── RAG Pipeline Node (`agent/rag_node.py`)
             ├── Vector Search (Chroma DB + Embeddings)
             ├── Context Injection (Formatted Markdown sources)
             ├── LLM Answer Generation
             └── Grounding Self-Check (Suppresses ungrounded claims)
       │
       ▼
 Structured Pydantic JSON Response (`ChatResponse`)
```

### Component Breakdown
* **FastAPI (`src/api/`)**: Provides async `/chat` and `/` health endpoints, validating requests with `ChatRequest` and returning structured `ChatResponse` schemas.
* **LangGraph (`src/agent/graph.py`)**: Implements an explicit state graph for routing ticket queries dynamically across Database Tools, RAG, Direct Responses, and Human Handoffs.
* **Database Tools (`src/tools/`)**: Typed, repository-backed tools for `get_job`, `get_customer`, and `get_open_invoices` querying SQLite.
* **RAG Pipeline (`src/agent/rag_node.py`)**: Decoupled vector retrieval, document chunking (`RecursiveCharacterTextSplitter`), prompt context injection, candidate answer generation, and grounding self-checks.
* **Grounding & Fallback**: Evaluates candidate answers against retrieved context using JSON self-verification. Returns `SAFE_FALLBACK_RESPONSE` if context is insufficient or ungrounded.
* **LLM Client (`src/llm/`)**: Uniform client interface supporting text generation, JSON mode, and schema parsing targeting Qwen 3.7.

---

## Day 3 HTTP client

`src/clients/http_client.py` provides a typed `HTTPClient` for the public JSONPlaceholder API:

- `GET /posts/{post_id}` returns a validated `ExternalPost`.
- `GET /users/{user_id}` returns a validated `ExternalUser`, including nested address and company models.

Pydantic strict models reject malformed or incorrectly typed payloads with `APIResponseValidationError`. HTTP 5xx responses and request timeouts are retried up to three times with exponential backoff. A 404 raises `ResourceNotFoundError`, while other 4xx responses raise `APIClientError`.

Run the Day 3 tests offline with:

```powershell
pytest tests/test_http_client.py
```

## Day 4 database layer

The SQLite database layer is defined in `db/schema.sql` and contains `customers`, `jobs`, `invoices`, and `tickets` tables. Foreign keys, status and priority checks, timestamps, indexes, and invoice amount checks are enforced by the schema.

Seed a local database with deterministic mock data:

```powershell
python db/seed.py
```

This creates `db/helpdesk.sqlite3` with 5 customers, 10 jobs, 10 invoices, and 10 support tickets. The query helpers in `src/db/queries.py` demonstrate category aggregation, customer/invoice joins, jobs-per-engineer grouping, and an overdue high-value customer subquery.

Run the database tests with:

```powershell
pytest tests/test_db.py
```

## Day 5 analytics notebook

Day 5 adds Pandas and NumPy analysis for the seeded SQLite data. Launch Jupyter from the repository root:

```powershell
jupyter notebook notebooks/01_data_exploration.ipynb
```

The notebook loads all four tables from `db/helpdesk.sqlite3`, analyzes ticket distributions, summarizes pending invoice revenue, measures engineer workload, and merges ticket, customer, and invoice data to find high-volume accounts with pending payments. The reusable functions are in `src/analytics/data_summary.py`.

Run the analytics tests with:

```powershell
pytest tests/test_analytics.py
```

## Day 6 JSON transcript storage

Day 6 adds a SQLite JSON document layer for unstructured support transcripts. `src/models_nosql.py` defines strict Pydantic schemas for transcript messages and metadata. `src/clients/nosql_client.py` provides transcript creation, retrieval, nested metadata updates, case-insensitive keyword search, and deletion using SQLite JSON functions.

Run the Day 6 tests with:

```powershell
pytest tests/test_nosql_client.py
```

## Day 7 data access layer

The unified `HelpdeskDataRepository` in `src/db/data_layer.py` bridges relational SQL records and JSON transcripts. It provides complete ticket context and customer overviews containing profiles, jobs, invoices, and transcript history.

Architecture:

```text
SQL: customers - tickets - jobs - invoices
                 \       /
                  HelpdeskDataRepository
                         |
              SQLite JSON: transcripts
```

Run the complete test suite with:

```powershell
pytest
ruff check .
ruff format --check .
```

## Day 8 ML ticket classifier

Day 8 adds a local scikit-learn triage pipeline in `src/ml/`. It trains separate
TF-IDF plus logistic-regression models for ticket category and priority, using
the SQLite tickets when available and a deterministic synthetic corpus when the
database is small. All classifiers use the canonical categories `technical`,
`billing`, `scheduling`, `warranty`, `cancellation`, and `general`; legacy
hardware, outage, network, access, and general-inquiry labels are migrated to
those values when old data is read.

Train and save the artifact with:

```powershell
python -m ml.train
```

The output is `models/ticket_classifier.joblib`. `TicketClassifier.predict()`
returns category, priority, a probability-based confidence score, and sets
`requires_llm_review` when the lower of the two model confidences is below
`0.60`. Accuracy and weighted F1, plus a classification report, are printed for
both targets during training. Treat the included synthetic holdout as a
reproducible smoke-test benchmark; production acceptance should include an
independently labelled validation set and calibration checks.

Run the ML tests with:

```powershell
pytest tests/test_classifier.py
```

## Day 9 escalation and routing rules

`src/rules/escalation_engine.py` combines the Day 8 ML prediction with ticket
text and customer billing context. It returns an immutable `EscalationResult`
with the destination queue, optional priority override, escalation state,
human-handoff state, and explainable reasons.

Active triggers are:

- ML confidence below `0.60`: `tier_1_manual_review` and human handoff.
- Overdue invoices above `$1,000` or `URGENT` priority: `vip_priority_queue`.
- `refund`, `chargeback`, `legal`, or `overcharge`: `billing_specialists` and
  human handoff.
- Otherwise, category queues route `technical`, `billing`, `scheduling`,
  `warranty`, `cancellation`, and `general` tickets to their standard support
  queues.

Financial disputes take queue precedence over VIP and manual-review routing so
that billing specialists receive the case directly; all matching conditions
remain visible in `reasons`.

Run the Day 9 tests with:

```powershell
pytest tests/test_escalation_engine.py
```

## Day 10 FastAPI service

Day 10 exposes the classifier and escalation engine through an asynchronous
FastAPI service. The application loads the ML model and unified data repository
at startup, with interactive Swagger documentation at `/docs`.

Start it locally from the repository root:

```powershell
uvicorn src.api.main:app --reload
```

Available endpoints include `GET /health`, `POST /api/v1/tickets/classify`,
and `GET /api/v1/tickets/{ticket_id}/context`. Run the API integration tests
with:

```powershell
pytest tests/test_api.py
```

## Day 11 Celery workers

Day 11 adds Celery tasks for ticket processing and customer notifications. The
default broker is Redis database 0 and the result backend is Redis database 1.
For local tests, Celery eager mode and `fakeredis` avoid requiring Docker.

Start a worker when Redis is available:

```powershell
celery -A src.workers.celery_app worker --loglevel=info
```

For local development without Docker or a Redis server, use fakeredis and the
Celery in-memory transport:

```powershell
$env:CELERY_USE_FAKE_REDIS="1"
celery -A src.workers.celery_app worker --loglevel=info --pool=solo
```

This mode is process-local and is intended for development and tests only.

Queue a ticket with `POST /api/v1/tickets/{ticket_id}/process-async`; the API
returns HTTP 202 with a task ID. Run worker tests with:

```powershell
pytest tests/test_workers.py
```

## Day 12 ticket-classification prompts

Day 12 adds versioned prompts in `prompts/ticket_classifier/`:
`v1.md`, `v2.md`, and `v3.md`. The prompt version is selected by the
classification service or LangChain chain rather than embedding prompt text in
Python code.

## Day 13 structured LLM output

`src/llm/structured_extract.py` uses the Day 11 `LLMClient` JSON mode and
Pydantic validation to produce a trusted `TicketClassification`. Categories and
priorities are constrained, confidence must be between `0.0` and `1.0`, and
invalid responses trigger bounded retries.

## Day 14 ticket-classification pipeline

`src/services/ticket_classifier.py` combines prompt loading, LLM extraction,
validation, and SQLite persistence. `classify_and_save()` writes only validated
category, priority, confidence, and escalation values through
`HelpdeskDataRepository`; invalid LLM output is never saved.

## Day 15 LangChain chain

`src/chains/ticket_chain.py` provides a LangChain equivalent using
`PromptTemplate`, runnable composition, and `PydanticOutputParser`.

## Day 16 database tools and function calling

`src/tools/` provides typed, repository-backed tools for `get_job`,
`get_customer`, and `get_open_invoices`.

## Days 18–19 Embeddings, Vector Search & RAG

`src/rag/ingest.py` and `src/agent/rag_node.py` implement document chunking, Chroma DB vector storage, `qwen3.7-text-embedding` retrieval, context injection, and LLM grounding self-checks.

## Day 20–21 FastAPI & End-to-End Agent Integration

Exposes `POST /chat` and `GET /` endpoints, integrating LangGraph agent routing, function calling, RAG retrieval, grounding self-verification, and structured Pydantic response models.

## Day 29 safety guardrails

`src/guardrails/` applies deterministic PII redaction, prompt-injection detection, refusal handling, and output checks around `HelpdeskAgent.invoke` without replacing authorization or rewriting the LangGraph. Adversarial cases live in `eval/adversarial_cases.csv` and run through `eval/run_langsmith_eval.py`.

## Multi-Tenant Database Architecture (Day 1)

### Overview
Extends the helpdesk platform to support isolated multi-tenant client companies. Every tenant-owned record is bound to a mandatory `tenant_id`, and tenant data isolation is enforced strictly at the database and service layer (`TenantDataService`).

### Model Relationships
- **Tenant**: Root entity representing a client company (`id`, `name`, `slug`, `is_active`, timestamps).
- **User**: User accounts (`tenant_id` nullable only for platform super-admins).
- **Customer**: Tenant customer profiles (`tenant_id`, `name`, `email`, `phone`).
- **Engineer**: Field technicians (`tenant_id`, `name`, `email`, `skills` JSON, `availability_status`).
- **Job**: Work orders (`tenant_id`, `customer_id`, `assigned_engineer_id`, status, priority).
- **Ticket**: Support requests (`tenant_id`, `customer_id`, `related_job_id`, intent, status, priority).
- **Invoice**: Billing records (`tenant_id`, `customer_id`, `job_id`, amount, status, due_date).
- **Conversation**: Email/chat thread (`tenant_id`, `customer_id`, `ticket_id`, status).
- **Message**: Individual exchange inside a conversation (`tenant_id`, `conversation_id`, `sender_type`, content).
- **AIConfiguration**: Tenant customization (`tenant_id`, `global_instructions`, `tone`, rules JSON).
- **KnowledgeDocument**: Tenant RAG document metadata (`tenant_id`, `name`, `file_path`, status).
- **AuditLog**: Audit entries tracking tenant operations and security events.

### Tenant Isolation Approach
- All queries filtered by `tenant_id` at the SQL / ORM level.
- Cross-tenant record linking (e.g. associating Tenant B's job with Tenant A's ticket) is blocked by validation checks in `TenantDataService`.
- Authorization checks occur in the data access layer independently of LLM prompt instructions or client-provided parameters.

### PostgreSQL & Environment Setup
Set the PostgreSQL connection URL environment variable:
```bash
export DATABASE_URL="postgresql://username:password@localhost:5432/helpdesk_db"
```

### Alembic Migration Commands
Run migrations to apply schema updates:
```powershell
# Apply all pending migrations to PostgreSQL / target database
alembic upgrade head

# Generate a new migration script when ORM models change
alembic revision --autogenerate -m "description_of_change"

# Rollback last migration step
alembic downgrade -1
```

### Testing Instructions
Run multi-tenant model and isolation tests:
```powershell
pytest tests/test_multi_tenant.py
```

---

## Client Dashboard & Management APIs (Day 4)

All Day 4 endpoints require a valid JWT `Authorization: Bearer <token>` header.
Tenant scope is derived exclusively from the authenticated user's `tenant_id` — no client-supplied tenant ID is trusted.

### Dashboard

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/dashboard/summary` | `tenant:read` | Aggregate metrics: customer count, open tickets, active jobs, pending invoices, available engineers |

**Example response:**
```json
{
  "customers": 42,
  "open_tickets": 7,
  "active_jobs": 3,
  "pending_invoices": 5,
  "available_engineers": 8
}
```

---

### Tickets — `/tickets`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/tickets` | `ticket:read` | Paginated list with optional `?status=`, `?priority=`, `?intent=`, `?customer_id=`, `?assigned_to=` filters |
| `GET` | `/tickets/{id}` | `ticket:read` | Get single ticket (tenant + customer isolation enforced) |
| `POST` | `/tickets` | `ticket:create` | Create ticket; validates `customer_id` and optional `related_job_id` belong to the tenant |
| `PATCH` | `/tickets/{id}` | `ticket:update` | Update `status`, `priority`, `handled_by`, `resolution`; sets `closed_at` on close/resolve |

---

### Jobs — `/jobs`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/jobs` | `job:read` | Paginated list with optional `?status=`, `?customer_id=` filters |
| `GET` | `/jobs/{id}` | `job:read` | Get single job |
| `POST` | `/jobs` | `job:create` | Create job; validates `customer_id` and `assigned_engineer_id` belong to the tenant |
| `PATCH` | `/jobs/{id}` | `job:update` | Update fields; enforces state machine transitions (`pending → assigned → in_progress → completed/cancelled`) |
| `POST` | `/jobs/{id}/assign` | `job:assign` | Assign engineer; validates engineer is within the tenant |
| `POST` | `/jobs/{id}/cancel` | `job:cancel` | Cancel job; completed jobs cannot be cancelled |

**Valid job status transitions:**
```
pending  → assigned, in_progress, cancelled
assigned → in_progress, completed, cancelled
in_progress → completed, cancelled
```

---

### Customers — `/customers`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/customers` | `customer:read` | Paginated list with optional `?search=` (name/email) |
| `GET` | `/customers/{id}` | `customer:read` | Get single customer (tenant isolation enforced) |
| `POST` | `/customers` | `customer:create` | Create customer; rejects duplicate email within tenant (409) |
| `PATCH` | `/customers/{id}` | `customer:update` | Update `name`, `email`, `phone`; guards against email collisions within tenant |

---

### Engineers — `/engineers`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/engineers` | `engineer:read` | Paginated list with optional `?status=` (availability) and `?search=` filters |
| `GET` | `/engineers/{id}` | `engineer:read` | Get single engineer (tenant isolation enforced) |
| `POST` | `/engineers` | `engineer:create` | Create engineer; validates `availability_status` and rejects duplicate email within tenant |
| `PATCH` | `/engineers/{id}` | `engineer:update` | Update `name`, `email`, `skills`, `availability_status` |

**Valid availability statuses:** `available`, `busy`, `on_leave`, `offline`

---

### Invoices — `/invoices`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/invoices` | `invoice:read` | Paginated list with optional `?status=`, `?customer_id=`, `?job_id=` filters |
| `GET` | `/invoices/{id}` | `invoice:read` | Get single invoice (tenant + customer isolation enforced) |
| `POST` | `/invoices` | `invoice:create` | Create invoice; validates `customer_id` and `job_id` belong to tenant and that the job belongs to the customer |
| `PATCH` | `/invoices/{id}` | `invoice:update` | Update `amount`, `status`, `due_date`; validates status transition |

**Valid invoice statuses:** `unpaid`, `paid`, `overdue`, `cancelled`

---

### Pagination

All list endpoints return a consistent paginated envelope:

```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "pages": 5
}
```

Query parameters: `?page=1&page_size=20` (max `page_size` is 100).

---

## Persistent LangGraph Conversation State (Day 6)

### Why persistent checkpointing is required

An in-memory checkpointer (e.g. `MemorySaver()`) keeps LangGraph state in RAM. The
state is therefore lost on every deploy, crash, or worker restart, and each API
process holds a *different* copy of the same conversation. That breaks follow-up
context, produces contradictory answers when requests are load-balanced across
workers, and makes multi-turn conversations unreliable.

Day 6 moves that state into PostgreSQL so a conversation can be resumed exactly
where it left off, by any process, after any restart.

### Storage backend

| Environment | Backend | Notes |
| --- | --- | --- |
| PostgreSQL (production) | `PostgresSaver` (`langgraph-checkpoint-postgres`) | Official LangGraph schema in the application database |
| SQLite (local dev / tests) | `SqliteSaver` (`langgraph-checkpoint-sqlite`) | Separate file: `db/langgraph_checkpoints.sqlite3` |

The saver is created in `src/agent/checkpointer.py` and is opened once during the
FastAPI lifespan, then handed to `HelpdeskAgent` when the graph is compiled:

```python
with open_persistent_checkpointer() as checkpointer:
    app.state.agent = HelpdeskAgent(..., checkpointer=checkpointer)
```

`HelpdeskAgent.invoke()` passes the thread id through the standard LangGraph
config. `conversation_id` **is** the `thread_id` — no second identifier is ever
generated:

```python
config = {"configurable": {"thread_id": conversation_id}}
graph.invoke(initial_state, config=config)
```

### Architecture

```text
Customer
   ↓
FastAPI
   ↓
Conversation
   ↓
conversation_id
   ↓
LangGraph thread_id
   ↓
Persistent Checkpointer
   ↓
PostgreSQL
```

Checkpoints are stored in LangGraph's own tables (`checkpoints`,
`checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`). These are kept
**separate** from the business `conversations` / `messages` tables: the message
table is the customer-visible transcript, while the checkpoint store is
internal graph state.

### Surviving application restarts

Because the thread id is derived from `conversation_id` and all state lives in
the database, a restart only requires re-opening the saver and recompiling the
graph. The next request with the same `conversation_id` transparently restores
the previous state. `tests/test_day6_persistence.py` proves this by exiting the
checkpointer context, opening a new saver against the same file, recompiling the
graph, and asserting the restored values.

### Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes (prod) | PostgreSQL URL; also used for checkpoints |
| `LANGGRAPH_DATABASE_URL` | no | Overrides the checkpoint database explicitly |
| `LANGGRAPH_SQLITE_PATH` | no | SQLite checkpoint file location (local only) |

When `DATABASE_URL` is PostgreSQL, checkpoints use the same database. When it is
SQLite, checkpoints go to a **separate** SQLite file so business tables stay
independent.

### Migration

The checkpoint schema is owned by LangGraph, not hand-written. The Alembic
migration `002_day6_checkpoints` replays `PostgresSaver.MIGRATIONS` so
deployments do not depend on application startup order, and it is a no-op on
SQLite. `PostgresSaver.setup()` remains idempotent and simply becomes a no-op
once Alembic has applied the schema.

```powershell
alembic upgrade head
```

Inspect the rendered SQL without touching a database:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/helpdesk_db"
alembic upgrade head --sql
```

`downgrade` removes only the LangGraph checkpoint tables; conversation and
message data are never dropped.

### Error handling

- Checkpoint store unavailable (connection loss, corrupt/locked database) → `503`
- Thread that cannot be safely resumed → `503`, never a silently forked thread
- Ownership / tenant checks run **before** the graph is invoked, so an
  unauthorized caller never reaches another customer's checkpoint.

### Running the persistence tests

```powershell
pytest tests/test_day6_persistence.py -v
```

## Verification Commands

```powershell
pytest
ruff check .
ruff format .
```
