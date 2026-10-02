# Optimization Plan: Reduce LLM Usage & Simplify Architecture

## Current LLM Call Map (per request)

### Legacy Graph (`src/agent/graph.py`) - **EVERY REQUEST**
1. `_decision_node()` → `generate_json()` for routing decision
2. `_final_node()` → `generate()` to format tool results into response

### Multi-Agent Flow (`src/agents/`) - **EVERY REQUEST**
3. `TriageAgent._llm_decision()` → `generate_json()` (optional refinement)
4. `SupervisorAgent.compose()` → `generate()` to "prettify" responses
5. `SupportAgent._generate()` → `generate()` for RAG answers
6. `HumanEscalationAgent._summarize()` → `generate()` for handover
7. `RAGGenerator.generate_answer()` → `generate()` for RAG answers
8. `GroundingChecker.check_grounding()` → `generate_json()` for verification

### API Services
9. `TicketClassifierService` → LLM structured extraction
10. `LangChain Chain` → LLM classification

---

## Target Architecture (Optimized)

```
Customer Message
      ↓
Normalize Text
      ↓
Rule/Keyword Classifier (deterministic) → Route: CANCEL_JOB, JOB_STATUS, etc.
      ↓
ML Classifier (TF-IDF) → Category + Priority + Confidence
      ↓
Confidence Gate (≥0.75 → deterministic, <0.75 → LLM fallback)
      ↓
┌─────────────────────────────────────────────────────────┐
│ ROUTING (no LLM):                                       │
│   - tool: get_job, cancel_job, etc.                    │
│   - handoff: disputes, safety, explicit human request  │
│   - rag: knowledge questions                           │
│   - respond: new service requests, general             │
└─────────────────────────────────────────────────────────┘
      ↓
Specialized Agent (deterministic tools + templates)
      ↓
RAG (ONLY for rag route, 1 LLM call with optional grounding)
      ↓
Template-based Response Generation (NO LLM for standard cases)
      ↓
END
```

---

## Changes to Implement

### 1. Remove LLM from Legacy Graph Decision Node
- File: `src/agent/graph.py`
- Replace `_decision_node()` LLM call with deterministic + ML logic (already exists in multi-agent triage)
- Remove `_final_node()` LLM call - use response templates

### 2. Intent-Aware RAG Gating
- File: `src/agent/graph.py` & `src/agents/specialists.py`
- Only invoke RAG when route == "rag"
- SupportAgent already does this correctly

### 3. Template-Based Response Generation
- Files: `src/agent/graph.py`, `src/agents/supervisor.py`, `src/agents/specialists.py`
- Create `ResponseTemplates` class with deterministic responses for:
  - Tool results (job found, invoice found, etc.)
  - Handoff messages
  - Confirmation messages
  - Error messages
- Only use LLM when response needs synthesis (RAG answers)

### 4. Remove Supervisor LLM Compose Call
- File: `src/agents/supervisor.py`
- `compose()` should return structured message directly
- Only use LLM if explicitly needed for complex synthesis

### 5. Remove Human Agent LLM Summary
- File: `src/agents/specialists.py`
- `HumanEscalationAgent._summarize()` → template

### 6. Optimize RAG Pipeline
- File: `src/agent/rag_node.py`
- Combine generate + grounding into single call (or make grounding optional)
- Reduce `k` from 3 to 2 for faster retrieval
- Add intent-based retrieval skipping

### 7. Reduce Conversation History
- Files: `src/agent/graph.py`, `src/agents/specialists.py`
- Limit to last 5 messages (configurable)
- Only send relevant context to each agent

### 8. Add LLM Usage Metrics
- File: `src/llm/client.py` or new `src/metrics/llm_metrics.py`
- Track: calls per request, fallback rate, tokens, latency

### 9. Remove Unused Code
- `src/chains/ticket_chain.py` - LangChain chain (unused)
- `src/services/ticket_classifier.py` - duplicate of ML classifier
- Legacy graph if multi-agent is primary (keep as fallback)

### 10. Configuration
- Add thresholds to config: `ML_CONFIDENCE_THRESHOLD`, `RAG_K`, `HISTORY_LIMIT`
- Make LLM fallback optional via env var

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/agent/graph.py` | Remove LLM from decide_node, final_node; add templates |
| `src/agents/triage.py` | Already good - deterministic first |
| `src/agents/supervisor.py` | Remove LLM from compose() |
| `src/agents/specialists.py` | Templates for responses; remove Human LLM |
| `src/agent/rag_node.py` | Single LLM call; configurable k; intent gating |
| `src/llm/client.py` | Add metrics wrapper |
| `src/api/main.py` | Config thresholds; remove unused services |
| `src/config.py` (new) | Centralized thresholds |

---

## Verification

After implementation:
```bash
ruff check .
ruff format .
pytest tests/test_agent_graph.py tests/test_conversation_memory.py tests/test_chat.py -v
pytest tests/test_agent_graph.py::test_respond_route_reaches_final_output -v
```

Manual verification flows:
- Cancel job → deterministic, no LLM
- Job status → deterministic tool call, template response
- General inquiry → RAG (1 LLM call)
- Billing dispute → handoff, no LLM
- Ambiguous request → LLM fallback
- Multi-turn conversation → history bounded
