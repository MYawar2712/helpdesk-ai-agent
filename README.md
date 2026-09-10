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

## Git workflow

```powershell
git status
git add .
git commit -m "Complete Day 1 project setup"
git push -u origin main
```
