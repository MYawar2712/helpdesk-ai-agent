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

## Git workflow

```powershell
git status
git add .
git commit -m "Complete Day 1 project setup"
git push -u origin main
```
