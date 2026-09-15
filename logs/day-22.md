# Day 22 Log: Evaluation Dataset & Rubric

Day 22 creates the evaluation dataset (`eval/golden_dataset.csv`) and scoring guide (`eval/rubric.md`) to enable automated benchmark evaluation in Day 23.

---

## 1. Golden Dataset (`eval/golden_dataset.csv`)

Created 25 structured test cases covering:
- **Job lookups** (`get_job`)
- **Customer lookups** (`get_customer`)
- **Invoice lookups** (`get_open_invoices`, `get_all_invoices`)
- **Knowledge-base / RAG questions** (Boiler pressure, AC cooling, billing address, electrical safety, warranty coverage, refund timeline)
- **Human handoff cases** (Dangerous electrical smell, legal dispute, gas leak emergency)
- **Ambiguous & off-topic queries** (Chocolate cake recipe, gibberish)
- **Ticket classification & direct responses** (Outage, billing, hardware, general inquiries)

Each case specifies:
`id`, `case_type`, `input_text`, `expected_route`, `expected_tool`, `expected_output_contains`, `requires_human_handoff`

---

## 2. Evaluation Rubric (`eval/rubric.md`)

Defined scoring dimensions:
- **Correctness** (40%): Route selection, tool execution accuracy, keyword presence.
- **Faithfulness & Grounding** (40%): Strict adherence to context and tool outputs without hallucinating claims.
- **Tone & Professionalism** (20%): Polite, clear, customer-centric support phrasing.

Formula:
$$\text{Composite Score} = (0.40 \times \text{Correctness}) + (0.40 \times \text{Faithfulness}) + (0.20 \times \text{Tone})$$

---

## 3. Dataset Validation Tests (`tests/test_eval_dataset.py`)

Built automated verification tests ensuring:
- `eval/golden_dataset.csv` exists and loads cleanly with CSV reader / pandas.
- Exactly 25 valid test cases present without empty required fields.
- Valid values for `expected_route` (`tool`, `rag`, `handoff`, `respond`).
- Valid boolean conversion for `requires_human_handoff`.
