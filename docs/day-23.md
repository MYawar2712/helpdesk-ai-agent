# Day 23 Log: LangSmith Tracing & Evaluation

Day 23 instruments the LangGraph helpdesk agent with LangSmith tracing and
runs an automated evaluation of all 25 golden-dataset cases using the Day 22
rubric.

---

## 1. LangSmith Tracing (`src/agent/tracing.py`)

Created `src/agent/tracing.py` providing:

- **`configure_tracing()`** — validates that `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, and `LANGCHAIN_PROJECT` are set; prints status to stdout.
- **`@traceable` re-export** — wraps the `langsmith.traceable` decorator so callers import only from `agent.tracing`; degrades to a no-op when `langsmith` is absent.
- **`wrap_agent_run(agent, ticket_text, *, metadata)`** — wraps a single `HelpdeskAgent.invoke()` call inside a named LangSmith run (`"helpdesk_agent_run"`) with per-case metadata (case_id, case_type, expected_route, expected_tool) visible in the LangSmith UI.

LangGraph emits internal node/LLM/tool-call spans automatically when
`LANGCHAIN_TRACING_V2=true` — no code changes to `graph.py` required.

---

## 2. Evaluation Runner (`eval/run_langsmith_eval.py`)

Standalone script that:

1. Loads `eval/golden_dataset.csv` (25 cases).
2. Instantiates a live `HelpdeskAgent` (SQLite + Chroma RAG).
3. Runs each case through `wrap_agent_run()` (tracing) or `agent.invoke()` (offline).
4. Scores each response against the Day 22 rubric:
   - **Correctness (40%)** — route match + keyword presence in `final_response`.
   - **Faithfulness (40%)** — `rag_result.is_grounded` for RAG routes; trust-pipeline for tool/handoff/respond.
   - **Tone (20%)** — heuristic polite-signal keyword counting.
5. Prints a per-case result table and a summary (pass count, avg composite score).
6. Lists failed cases with actual vs expected route and composite score.
7. Prints LangSmith trace URL when tracing is active.
8. Exits with code 1 when any case fails (CI-friendly).

---

## 3. Environment Variables (`.env` / `.env.example`)

Added three new keys documented in both files:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=YOUR_LANGSMITH_API_KEY_HERE   # from smith.langchain.com
LANGCHAIN_PROJECT=helpdesk-ai-agent
```

> **Action required**: replace `YOUR_LANGSMITH_API_KEY_HERE` in `.env` with
> your real key from https://smith.langchain.com/ → Settings → API Keys.

---

## 4. Tests (`tests/test_langsmith_eval.py`)

19 unit tests covering:

- `configure_tracing()` — enabled / disabled / missing-key branches.
- `wrap_agent_run()` — correct delegation to `agent.invoke()`, metadata passthrough.
- `_score_correctness()` — full-pass, partial, fail, no-keyword cases.
- `_score_faithfulness()` — grounded / ungrounded RAG; non-RAG routes.
- `_score_tone()` — polite, rude, empty responses.
- `load_dataset()` — real CSV (25 rows), missing file, empty file.

**Result: 19/19 passed.**

---

## 5. Inspecting Traces for Failed Cases

Once `LANGCHAIN_API_KEY` is set:

1. Run `python eval/run_langsmith_eval.py` — it prints the LangSmith project URL.
2. Open https://smith.langchain.com/ and select project `helpdesk-ai-agent`.
3. Each failed run shows the full trace: `decide` node JSON output, tool input/output, RAG retrieval chunks and grounding verdict.
4. Use the trace to diagnose routing errors (LLM chose wrong route), missing keywords in tool responses, or RAG grounding failures.
