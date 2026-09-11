# Day 10: FastAPI service layer

Day 10 exposes classification, routing, health, and ticket-context retrieval
through an asynchronous FastAPI application.

Endpoints:

- `GET /health` reports service and model readiness.
- `POST /api/v1/tickets/classify` classifies and routes new tickets.
- `GET /api/v1/tickets/{ticket_id}/context` returns SQL and transcript context.

The application loads the classifier and unified data repository during startup.
Swagger documentation is available at `/docs`.

Start the service with:

```powershell
python -m uvicorn src.api.main:app --reload
```
