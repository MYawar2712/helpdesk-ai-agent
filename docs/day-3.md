# Day 3: HTTP client and external API validation

## What I implemented

Day 3 added `src/clients/http_client.py`, a typed HTTP client for the public JSONPlaceholder API. The client supports:

- `GET /posts/{post_id}` through `fetch_post()`
- `GET /users/{user_id}` through `fetch_user()`
- Strict Pydantic v2 schemas for posts, users, addresses, and companies
- Positive-integer ID validation
- Configurable request timeouts and retry attempts

The JSONPlaceholder `userId` field is mapped to the Python `user_id` field using a Pydantic validation alias. Unknown fields and incorrect types are rejected.

## Error handling and retries

The client raises specific exceptions for failure categories:

- `ResourceNotFoundError` for HTTP 404 responses
- `APIClientError` for other HTTP 4xx responses
- `APIResponseValidationError` for malformed JSON or invalid response payloads

Connection errors, timeouts, and HTTP 5xx responses are retried with exponential backoff. The maximum number of attempts is configurable through `HTTPClient(max_attempts=...)`.

## Tests

`tests/test_http_client.py` uses the `responses` library, so the tests do not contact the real internet. It covers successful post and user requests, nested response validation, malformed JSON, invalid payloads, 404 handling, 500 retry behavior, invalid IDs, and invalid client configuration.

The full test suite completed with:

```text
20 passed
```

Ruff also completed successfully:

```text
All checks passed!
```

## Dependencies

Day 3 added these dependencies to `requirements.txt`:

- `requests` for HTTP requests
- `pydantic` for strict response schemas
- `tenacity` for retry behavior
- `responses` for offline HTTP mocking in tests

Run the Day 3 tests with:

```powershell
pytest tests/test_http_client.py
```
