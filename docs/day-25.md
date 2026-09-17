# Day 25: Docker & GitHub Actions CI

## Overview

Day 25 containerises the existing FastAPI application using Docker and adds a
GitHub Actions CI pipeline that runs on every push. No application code,
tests, or configuration files were modified.

---

## Docker Setup

### Base Image

`python:3.11-slim` was chosen because:

- Matches the `requires-python = ">=3.11"` constraint in `pyproject.toml`.
- `slim` (Debian/glibc) is required by binary dependencies — `numpy`,
  `scikit-learn`, and `chromadb` — that do not ship `muslc` wheels and would
  fail on `python:3.11-alpine`.
- Significantly smaller than the full `python:3.11` image while remaining fully
  compatible.

### Layer Strategy

```
COPY requirements.txt → pip install (cached layer)
COPY pyproject.toml + src/ → pip install -e . (editable install)
COPY models/ prompts/ db/schema.sql db/seed.py
```

Placing dependency installation before the source copy means Docker reuses the
cached `pip install` layer on every rebuild that only touches source files,
keeping iteration fast.

### Editable Install (`pip install -e .`)

The project uses top-level `src/` imports throughout (e.g. `from agent.graph
import HelpdeskAgent`). Installing the local package in editable mode mirrors
the `pythonpath = [".", "src"]` setting in `pyproject.toml` used by pytest and
makes all internal imports resolve correctly without patching `sys.path` in the
entrypoint.

### Runtime Assets Included

| Path | Reason |
|------|--------|
| `models/ticket_classifier.joblib` | Pre-trained ML classifier needed by `/health` and `/api/v1/tickets/classify` |
| `prompts/ticket_classifier/` | Prompt templates used by LangChain chains |
| `db/schema.sql`, `db/seed.py` | SQLite schema and seed data; the database file is created at startup by `initialize_database()` |

### Runtime Assets Excluded (via `.dockerignore`)

| Path | Reason |
|------|--------|
| `data/` | Chroma vector-store — large and re-built at runtime |
| `.env` / `.env.*` | Secrets must be injected via `--env-file` or environment variables |
| `tests/` | Not needed at runtime; reduces image size |
| `.venv/`, `__pycache__/`, `*.egg-info/` | Build artefacts |

### Entrypoint

```
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`src.api.main:app` works from `/app` because the editable install registers
`src/` on the Python path. `main.py` also inserts `src/` into `sys.path` at
import time as a belt-and-suspenders guard.

### Port

`EXPOSE 8000` — standard Uvicorn default.

---

## GitHub Actions CI Workflow

File: `.github/workflows/ci.yml`

### Trigger

```yaml
on:
  push:
    branches: ["**"]
```

Runs on every push to any branch.

### Pipeline Steps

```
push
  └─ Checkout (actions/checkout@v4)
       └─ Set up Python 3.11 (actions/setup-python@v5)
            └─ Install dependencies (pip install -r requirements.txt && pip install -e .)
                 └─ Lint (ruff check .)
                      └─ Test (pytest)
                           └─ Docker build (docker build -t helpdesk-ai-agent .)
```

Each step depends on the previous; the workflow fails fast if any step fails.

### Linter

`ruff check .` — uses the project's existing `[tool.ruff]` configuration in
`pyproject.toml` (line length 88, `target-version = "py311"`, rule sets
`E F I UP B`). No new tooling is introduced.

### Tests

`pytest` — uses the project's `[tool.pytest.ini_options]` in `pyproject.toml`
directly. LLM and LangSmith environment variables are passed from GitHub Actions
Secrets. Tests mock external API calls so the suite passes even when secrets are
absent or empty.

### Secrets Required (Optional)

| Secret | Purpose |
|--------|---------|
| `LLM_API_KEY` | LLM provider key (tests mock this) |
| `LLM_MODEL` | Model name |
| `LLM_BASE_URL` | Provider base URL |
| `LANGCHAIN_API_KEY` | LangSmith tracing (tracing disabled in CI via `LANGCHAIN_TRACING_V2=false`) |

---

## Build & Run Commands

### Build

```bash
docker build -t helpdesk-ai-agent .
```

### Run

```bash
# With a local .env file
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name hd-agent \
  helpdesk-ai-agent
```

### Verify

```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0","models_loaded":true}

curl http://localhost:8000/
# → {"status":"ok","message":"Helpdesk AI Agent API","version":"0.1.0"}
```

### Stop & Remove

```bash
docker rm -f hd-agent
```
