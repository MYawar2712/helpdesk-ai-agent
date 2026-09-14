# Day 18: Embeddings and Vector Search

## Implemented

- Added 18 realistic, high-quality support articles under `docs/knowledge_base/` covering technical troubleshooting, billing queries, appointments, safety, and warranties.
- Configured **Chroma** as local vector storage persisted in `data/chroma_helpdesk`.
- Integrated embedding model creation using `qwen3.7-text-embedding` configured via `LLM_API_KEY` and `LLM_BASE_URL` from runtime `LLMConfig`.
- Built `src/rag/ingest.py` with modular functions:
  - `load_knowledge_articles()`: Reads markdown files and attaches metadata (`source`, `title`, `topic`).
  - `create_embedding_model()`: Instantiates `OpenAIEmbeddings` targeting `qwen3.7-text-embedding`.
  - `ingest_knowledge_base()`: Embeds knowledge documents into Chroma with unique doc identifiers.
  - `search_knowledge_base()`: Similarity search returning top-k relevant support documents.
- Created unit tests in `tests/test_rag_ingest.py` using `FakeEmbeddings` to run tests locally without calling remote LLM API endpoints.

## What Worked

- Markdown articles parse cleanly with structured front-matter titles and topics.
- Chroma handles local vector storage efficiently without external DB dependencies.
- Deterministic test suite validates ingestion and vector retrieval while passing all 105 pytest test cases.

## What Could Be Improved

- Add metadata filtering options (e.g. filter by topic/category) directly in `search_knowledge_base()`.
- Implement dynamic document chunking (e.g. `RecursiveCharacterTextSplitter`) for long multi-section articles.
- Add cosine score thresholding for retrieval relevance in Day 19's agent graph integration.

## Configuration

The real embedding client utilizes the same API key and base URL as the core LLM client, targeting `qwen3.7-text-embedding`. All test suites use deterministic mock embeddings to isolate tests and preserve API quota.
