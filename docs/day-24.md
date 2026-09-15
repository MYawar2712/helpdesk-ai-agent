# Day 24: PromptFoo evaluation

## Implemented

- Added `eval/promptfoo/promptfooconfig.yaml` for the requested side-by-side V1,
  V2, and V3 comparison.
- Added root-level `eval/promptfoo.yaml` for the same evaluation layout.
- Added 12 representative test cases in `eval/test_cases.yaml` covering common
  categories, ambiguity, and an off-topic edge case.
- Added `eval/README.md` with setup, execution, scoring, and secret-handling
  instructions.

## What worked

The configurations reuse the Day 12 prompt files and apply the same test cases
to every prompt. Assertions check the expected category and reject outputs that
are not one of the six allowed labels.

The PromptFoo run completed successfully after correcting two configuration
issues: prompt files must be referenced as `file://...` entries, and PromptFoo
uses `{{env.NAME}}` for environment interpolation. The final run used the
configured `qwen-flash` endpoint and produced 34 passes, 2 failures, and 0
errors across 36 prompt/test combinations.

V1 and V3 passed all 12 cases. V2 missed the two scheduling cases because it
returned the correct word with Markdown code formatting (for example,
`` `scheduling` ``), which failed the exact-output assertion.

## Verification

PromptFoo output was written to `eval/promptfoo/results.json`. V1 and V3 are
currently tied for best performance at 100% (12/12). No production behavior
was changed for Day 24.
