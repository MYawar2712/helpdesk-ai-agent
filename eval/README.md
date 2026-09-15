# PromptFoo evaluation

This suite compares the Day 12 ticket-classifier prompts V1, V2, and V3 using
the same representative support-ticket cases. PromptFoo runs every case once
against each prompt, side by side.

The suite measures:

- classification correctness through the expected-category assertions;
- output validity through the allowed-category JavaScript assertion;
- prompt consistency by comparing pass rates and results across V1, V2, and V3;
- failures and edge cases, including ambiguous and off-topic requests.

## Setup

Install PromptFoo with Node.js/npm, then configure the existing provider values:

```powershell
npm install -g promptfoo
$env:OPENAI_API_KEY = $env:LLM_API_KEY
$env:OPENAI_API_BASE_URL = $env:LLM_BASE_URL
```

PromptFoo reads `LLM_MODEL`, `LLM_BASE_URL`, and `LLM_API_KEY` from the
environment in `promptfooconfig.yaml`. Keep real keys in `.env`; never commit
them.

## Run

From the repository root:

```powershell
promptfoo eval -c eval/promptfoo/promptfooconfig.yaml
promptfoo view
```

The root-level `eval/promptfoo.yaml` is also provided as a convenient config
when running from inside `eval/` or when a flat evaluation layout is preferred.

PromptFoo's comparison table shows each prompt's pass rate, latency, and token
usage. The best prompt is the one with the highest correctness and valid-output
rate, with consistency and latency used as tie-breakers. The result is model
and provider-dependent, so this repository does not hard-code a winner.

## Offline checks

PromptFoo requires Node.js and makes live LLM calls. The Python test suite does
not make provider calls:

```powershell
pytest tests/test_eval_dataset.py tests/test_langsmith_eval.py -q
```

The dataset and rubric used here are [golden_dataset.csv](golden_dataset.csv)
and [rubric.md](rubric.md). PromptFoo focuses specifically on prompt-version
comparison, while the LangSmith evaluator scores the complete agent pipeline.
