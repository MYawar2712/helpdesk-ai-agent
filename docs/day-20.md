# Day 20: FastAPI & Async

Day 20 exposes the helpdesk agent via an asynchronous REST API built with FastAPI and Pydantic.

## Flow

```text
POST /chat
     ↓
FastAPI Router
     ↓
LangGraph Agent
 ├── Database Tools
 └── RAG Pipeline
     ↓
Structured Response (ChatResponse)
```

## Endpoints

### 1. `GET /`
Returns service health and API version metadata:
```json
{
  "status": "ok",
  "message": "Helpdesk AI Agent API",
  "version": "0.1.0"
}
```

### 2. `POST /chat`
Submits a user prompt or support ticket to the underlying LangGraph agent.

#### Request Schema (`ChatRequest`)
```json
{
  "message": "What is the warranty policy for AC repairs?"
}
```

#### Response Schema (`ChatResponse`)
```json
{
  "response": "AC repairs are covered for 2 years under warranty.",
  "route": "rag",
  "tool_name": null,
  "tool_result": null,
  "sources": ["warranty_coverage.md"]
}
```

## Error Handling & Async Execution

- **Async Handling**: Endpoints use `async def` and non-blocking executor wrappers (`asyncio.to_thread()`) to process LangGraph graph invocations without blocking the event loop.
- **Validation Errors**: Empty or whitespace-only messages raise HTTP `422 Unprocessable Entity`.
- **Runtime Exceptions**: LLM or agent runtime errors are caught and returned cleanly as HTTP `500 Internal Server Error`.
