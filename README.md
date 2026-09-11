# helpdesk-ai-agent

A small, typed Python foundation for building and evaluating a helpdesk AI agent. Day 1 establishes the project layout, virtual-environment workflow, Git hygiene, pre-commit checks, and a simple domain class.

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

The package source lives in `src/`, tests in `tests/`, documentation in `docs/`, reusable prompts in `prompts/`, and evaluation material in `eval/`.

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
database is small. Database `network` and `access` labels are mapped to the
current `outage` and `general_inquiry` categories.

Train and save the artifact with:

```powershell
python -m ml.train
```

The output is `models/ticket_classifier.joblib`. `TicketClassifier.predict()`
returns category, priority, a probability-based confidence score, and sets
`requires_llm_review` when the lower of the two model confidences is below
`0.60`. Accuracy and weighted F1, plus a classification report, are printed for
both targets during training. The local baseline should normally exceed 0.80
on the included synthetic holdout; production acceptance should also include
an independently labelled validation set and calibration checks.

Run the ML tests with:

```powershell
pytest tests/test_classifier.py
```

## Git workflow

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
- Otherwise, category queues route billing, outage, hardware, and general
  inquiry tickets to their standard support queues.

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

```powershell
git status
git add .
git commit -m "Complete Day 1 project setup"
git push -u origin main
```
