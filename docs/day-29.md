# Day 29: Safety Guardrails

Day 29 adds a deterministic safety layer around the existing LangGraph
helpdesk agent. The agent graph, tools, RAG pipeline, authentication,
customer isolation, and business rules are unchanged. Guardrails wrap
`HelpdeskAgent.invoke` so unsafe input is stopped before routing or tool
calls, and the final text is checked before it is returned.

This layer reduces risk. It does not make the system completely secure.

## Guardrail architecture

```text
User Input
   ↓
Input Guardrails   (PII redact, injection, refusal)
   ↓
Existing Agent     (decide → tool / RAG / respond / handoff)
   ↓
Tools / RAG        (authorization still enforced independently)
   ↓
Output Guardrails  (PII redact, secret/prompt leak, hallucinated actions)
   ↓
Final Response
```

Implementation:

- `src/guardrails/checks.py` — reusable checks
- `src/guardrails/__init__.py` — public exports
- `HelpdeskAgent.invoke` in `src/agent/graph.py` — the integration point
- `POST /chat` exposes `refused` and `refusal_reason` on `ChatResponse`

The safest integration point is `invoke`, because every HTTP and evaluation
path already calls it. Input checks run before `graph.invoke`, so a refused
request never reaches the decision node, tools, or RAG. Output checks run on
`final_response` after the existing graph finishes.

Functions:

| Function | Role |
| --- | --- |
| `check_input()` | Orchestrates inbound redaction, injection, and refusal |
| `detect_pii()` | Finds email, phone, card, SSN, and ID-like spans |
| `redact_pii()` | Replaces spans with type labels |
| `detect_prompt_injection()` | Rule-based jailbreak / override detection |
| `should_refuse()` | Policy decision with a short reason |
| `check_output()` | Validates the final assistant text |

Security decisions are regex- and policy-based, not delegated to the LLM.

## PII detection and redaction

Common patterns are detected and replaced:

- Email → `[REDACTED_EMAIL]`
- Phone → `[REDACTED_PHONE]`
- Luhn-valid card-like numbers → `[REDACTED_CARD]` (and the request is refused)
- US SSN → `[REDACTED_SSN]`
- UK NINo / passport-like IDs after an explicit label → `[REDACTED_ID]`

`detect_pii` stores span offsets and types only. Application logs record
types and counts, never the original value. Evaluation result JSON stores
redacted previews only.

Example: `My email is user@example.com` becomes
`My email is [REDACTED_EMAIL]`.

## Refusal handling

Unsafe, unauthorized, jailbreak, secret-disclosure, forged-identity, and
fake-completion requests return a structured state:

- `route`: `respond` (no new graph route; the agent is not redesigned)
- `tool_name` empty, `tool_result` empty — tools are not executed
- `guardrail_refused`: `true`
- `guardrail_reason` / `guardrail_category`
- `final_response`: a short, predictable refusal that explains why and
  states that authorization will not be bypassed

The LLM is not called for refused input.

## Prompt-injection protection

Deterministic rules catch attempts to ignore system instructions, inject
`<system>` tags, enable jailbreak/DAN/developer mode, bypass authorization,
or demand hidden prompts. A match refuses the request before tools run.

Guardrails do **not** replace authorization. `HelpdeskOperationsService`,
MCP `customer_id` checks, and tool argument validation still apply even if
text-based detection misses a case.

## Output validation

Before a response is returned, `check_output`:

- Redacts remaining PII in the assistant text (and nested `tool_result` strings
  when PII types were found)
- Blocks credential-like material and leaked routing/system prompt fragments
- Blocks responses that appear to dump two customers' records together
- Blocks claims that a refund/deletion/mass lock completed when no tool ran

Ordinary scheduling confirmations that go through the existing agent are not
treated as refund/deletion hallucinations.

## Adversarial test categories

`eval/adversarial_cases.csv` (columns: `input,expected_behavior,category`)
covers:

- PII exposure
- Prompt injection
- Jailbreak attempts
- Cross-customer data access
- Unauthorized job access
- Unauthorized tool execution
- Fake/forged customer identity
- Requests to reveal system prompts
- Requests to reveal secrets
- Unsafe instructions
- Hallucinated actions
- Malicious or conflicting instructions

`expected_behavior` is `refuse` or `redact_pii`.

## Evaluation

`eval/run_langsmith_eval.py` still runs `eval/golden_dataset.csv` unchanged,
then runs the adversarial file. Flags: `--golden-only`, `--adversarial-only`.

Each adversarial case is recorded as PASS or FAIL with a short failure
reason. Original sensitive values are not written to result JSON.

## Known limitations

- Pattern matching misses obfuscated PII (images, encodings, nicknames, full
  street addresses) and novel jailbreaks (Base64, many-shot, low-resource
  languages).
- `HelpdeskAgent.invoke` has no authenticated customer identity; isolation
  remains the job of operations/MCP/API authorization.
- Output checks cannot undo a tool that already ran; input refusal is what
  prevents unauthorized tool use on detected attacks.
- Seed-name heuristics for cross-customer dumps are narrow.
- The system is **not** completely secure.
