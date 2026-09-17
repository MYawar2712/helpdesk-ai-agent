# Day 25: Docker & GitHub Actions CI — Work Log

## Files Created

| File | Purpose |
|------|---------|
| `Dockerfile` | Containerises the FastAPI app |
| `.dockerignore` | Excludes venvs, secrets, tests, caches from build context |
| `.github/workflows/ci.yml` | GitHub Actions pipeline |
| `docs/day-25.md` | Technical documentation |
| `logs/day-25.md` | This log |

---

## Commands Run

### Lint

```bash
.venv\Scripts\ruff check .
# All checks passed!
```

### Tests

```bash
.venv\Scripts\pytest --tb=short -q
# 190 passed, 1 warning in 23.77s
```

### Docker Build

```bash
docker build -t helpdesk-ai-agent .
```

### Docker Run & Verify

```bash
docker run -d -p 8000:8000 --env-file .env --name hd-agent helpdesk-ai-agent
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","models_loaded":true}
curl http://localhost:8000/
# {"status":"ok","message":"Helpdesk AI Agent API","version":"0.1.0"}
docker rm -f hd-agent
```

---

## Problems Encountered & Fixes

### 1. `ruff` not on system PATH

**Problem:** Running `ruff check .` directly in PowerShell failed with
`CommandNotFoundException` because `ruff` is installed inside `.venv`, not
globally.

**Fix:** Invoked via `.venv\Scripts\ruff check .`. In CI this is not an issue
because `pip install -r requirements.txt` installs `ruff` into the GitHub
Actions Python environment and it lands on `PATH` automatically.

### 2. Editable install required for src/ imports

**Problem:** The Dockerfile initially only copied `src/` and ran `uvicorn
src.api.main:app`. The internal imports (e.g. `from agent.graph import
HelpdeskAgent`) rely on `src/` being on `sys.path`.

**Fix:** Added `pip install -e .` after copying `pyproject.toml` and `src/`.
This registers the package in site-packages and puts `src/` on `sys.path` — the
same approach used by pytest (`pythonpath = [".", "src"]` in `pyproject.toml`).
`main.py` also inserts `src/` at import time as a fallback.

### 3. data/ directory excluded — Chroma vector store not pre-baked

**Problem:** The `data/chroma_helpdesk` Chroma vector store is in `.gitignore`
and excluded from the Docker build context via `.dockerignore`. Routes that
trigger RAG lookups will rebuild the store at first use.

**Note:** This is expected behaviour. The store is ephemeral by design (Day 18).
For a production deployment, mount the vector store as a volume or add an
ingestion step to the Docker entrypoint.

---

## Verification Results

| Check | Result |
|-------|--------|
| `ruff check .` | ✅ All checks passed |
| `pytest` (190 tests) | ✅ 190 passed, 1 warning |
| `docker build -t helpdesk-ai-agent .` | ✅ Build succeeded (11 layers, ~4 min first run) |
| `GET /health` (container) | ✅ `{"status":"ok","version":"0.1.0","models_loaded":true}` |
| `GET /` (container) | ✅ `{"status":"ok","message":"Helpdesk AI Agent API","version":"0.1.0"}` |
