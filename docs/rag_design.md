# RAG Pipeline Architecture & Design (`rag_design.md`)

This document outlines the architecture, chunking strategy, vector retrieval, prompt context injection, and grounding self-check mechanisms implemented in `src/agent/rag_node.py` for Day 19.

## Flow Architecture

```text
User Support Question
       │
       ▼
   Embedding (Qwen 3.7)
       │
       ▼
  Vector Search (Chroma DB)
       │
       ▼
 Relevant Knowledge Chunks
       │
       ▼
 Prompt Context Injection
       │
       ▼
    LLM Answer Generation
       │
       ▼
  Grounding Self-Check (LLM JSON)
       ├── Grounded ──► Return LLM Answer
       └── Ungrounded / Insufficient ──► Return Safe Fallback Response
```

---

## 1. Document & Chunking Strategy

* **Knowledge Base Size**: 18 markdown documents under `docs/knowledge_base/` covering HVAC, plumbing, billing, warranties, appointments, and safety procedures.
* **Chunking Algorithm**: `RecursiveCharacterTextSplitter` configured with:
  * `chunk_size`: 400 characters.
  * `chunk_overlap`: 50 characters.
  * `separators`: `["\n\n", "\n", " ", ""]`.
* **Metadata Retention**: Each chunk preserves original document metadata including `source` filename, article `title`, and topic `category`.

---

## 2. Vector Retrieval Approach

* **Storage Engine**: Local Chroma vector database (`data/chroma_helpdesk`).
* **Embeddings**: `qwen3.7-text-embedding` initialized using `LLMConfig`.
* **Search Strategy**: $k$-Nearest Neighbors ($k=3$) similarity search executed via `RAGRetriever.retrieve()`.
* **Decoupling**: `RAGRetriever` operates independently of prompt formatting and LLM generation logic.

---

## 3. Context Injection

* **Formatting**: `RAGGenerator.format_context()` structures retrieved chunks into explicit, labeled source blocks:
  ```text
  [Source 1: Boiler Low Pressure Troubleshooting (boiler_pressure_low.md)]
  If boiler pressure drops below 1.0 bar, locate the filling loop...
  ```
* **Prompt Engineering**: The injected system prompt enforces strict adherence to provided context:
  > *"Answer the customer question strictly using ONLY the provided knowledge-base context. If the context does not contain enough information to answer the question, state clearly that the knowledge base does not contain sufficient details."*

---

## 4. Grounding Self-Check & Fallback Behavior

* **Self-Check Engine**: `GroundingChecker.check_grounding()` invokes the LLM with structured JSON output requirements (`is_grounded: bool`, `reason: str`).
* **Verification Rules**:
  1. If no relevant chunks were retrieved, grounding automatically fails.
  2. If candidate answer contains facts or claims outside the retrieved context, `is_grounded` resolves to `False`.
  3. If `is_grounded` is `False` or execution fails, `RAGNode` suppresses the hallucinated text and substitutes `SAFE_FALLBACK_RESPONSE`:
     > *"I'm sorry, but I don't have enough information in the knowledge base to answer your question accurately. Please contact human support for assistance."*
