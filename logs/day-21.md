# Week 3 Log & Review: RAG Pipeline, Tools & Agent Integration

Week 3 focuses on building and integrating a complete, production-ready Helpdesk AI Agent combining **LangChain Composition**, **Database Function Calling**, **Embeddings & Chroma Vector Search**, **RAG Grounding Self-Checks**, and **FastAPI Async Endpoints**.

---

## Architecture Overview

```text
HTTP Request (POST /chat)
       │
       ▼
 FastAPI Router (`src/api/routes.py`)
       │
       ▼
 LangGraph Agent (`src/agent/graph.py`)
       ├── Decision Node (Routes: tool | rag | respond | handoff)
       │
       ├── Database Tool Calling (`get_job`, `get_customer`, `get_open_invoices`)
       │
       └── RAG Pipeline (`src/agent/rag_node.py`)
             ├── Chroma Vector Search & Embeddings
             ├── Context Injection
             ├── LLM Answer Generation
             └── Grounding Self-Check (Suppresses ungrounded claims)
       │
       ▼
 Structured Pydantic Response (`ChatResponse`)
```

---

## Daily Milestone Breakdown

### Day 15 — LangChain Chain Composition
- Implemented `src/chains/ticket_chain.py` using `PromptTemplate`, Runnable composition, and `PydanticOutputParser`.
- Standardized ticket classification output (`category`, `priority`, `confidence_score`).

### Day 16 — Database Tools & Function Calling
- Built typed, repository-backed database tools: `get_job`, `get_customer`, and `get_open_invoices`.
- Built `ToolCallingAssistant` handling LLM tool calls and sending JSON results back to the LLM for natural language answers.

### Day 17 — LangGraph Agent State Graph
- Built stateful agent graph (`HelpdeskAgent`) in `src/agent/graph.py` managing state transitions across decision, tool execution, direct response, and human handoff nodes.

### Day 18 — Embeddings & Vector Search
- Created 18 markdown support articles in `docs/knowledge_base/`.
- Configured local persistent vector storage using **Chroma** (`data/chroma_helpdesk`) and `qwen3.7-text-embedding`.

### Day 19 — RAG Pipeline, Chunking & Grounding
- Implemented `src/agent/rag_node.py` and `docs/rag_design.md`.
- Added document chunking (`RecursiveCharacterTextSplitter`), prompt context injection, candidate answer generation, and `GroundingChecker` LLM self-verification.
- Enforced `SAFE_FALLBACK_RESPONSE` when knowledge-base context is insufficient or ungrounded.

### Day 20 — FastAPI & Async
- Created `POST /chat` and `GET /` endpoints in `src/api/routes.py` with `ChatRequest` and `ChatResponse` schemas.
- Implemented async execution using `asyncio.to_thread` and HTTP 422 / 500 status code handling.

### Day 21 — Week 3 Integration & Review
- Integrated RAG execution node directly into `HelpdeskAgent` LangGraph state machine.
- Created end-to-end integration test suite (`tests/test_integration.py`).
- Verified all 122 pytest test cases pass cleanly.
- Updated `README.md` and tagged Git release `v0.3-rag-agent`.

---

## Test & Quality Verification

- **Pytest**: 122 / 122 tests passed (100% green).
- **Ruff Linter**: All checks passed cleanly.
- **Git Tag**: `v0.3-rag-agent`
