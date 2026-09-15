# Evaluation Rubric & Scoring Guide (`rubric.md`)

This rubric defines the quantitative and qualitative evaluation framework for assessing the `helpdesk-ai-agent` against `eval/golden_dataset.csv`.

---

## Evaluation Dimensions

### 1. Correctness (Weight: 40%)
* **Definition**: Does the response answer the user's inquiry accurately and route to the correct tool, RAG node, or human handoff?
* **Scoring Criteria (1 to 5)**:
  - **5 (Pass)**: Route matches `expected_route`, tool matches `expected_tool`, and output contains expected keywords.
  - **3 (Partial Pass)**: Correct route selected, but minor omissions or details missing from answer.
  - **1 (Fail)**: Incorrect route selected, incorrect tool executed, or wrong factual answer.

---

### 2. Faithfulness & Grounding (Weight: 40%)
* **Definition**: Is the generated response strictly supported by retrieved knowledge-base context or database tool output, without hallucinating unsupported claims?
* **Scoring Criteria (1 to 5)**:
  - **5 (Pass)**: Answer contains only claims directly backed by vector context or tool results.
  - **3 (Partial Pass)**: Answer is factually accurate but includes mild ungrounded assumptions.
  - **1 (Fail)**: Answer contains explicit hallucinations or fails the grounding self-check.

---

### 3. Tone & Professionalism (Weight: 20%)
* **Definition**: Is the language polite, concise, clear, and appropriate for technical support?
* **Scoring Criteria (1 to 5)**:
  - **5 (Pass)**: Professional, helpful, customer-centric tone with clear structure.
  - **3 (Partial Pass)**: Overly robotic or slightly informal phrasing.
  - **1 (Fail)**: Rude, unhelpful, or incoherent output.

---

## Composite Score Formula

$$\text{Composite Score} = (0.40 \times \text{Correctness}) + (0.40 \times \text{Faithfulness}) + (0.20 \times \text{Tone})$$

A test case is considered **Passing** if the Composite Score is $\ge 4.0 / 5.0$.

---

## Route-Specific Passing Expectations

| Expected Route | Action | Expected Agent Outcome |
| :--- | :--- | :--- |
| `tool` | Execute database tool | Execute `get_job`, `get_customer`, `get_open_invoices`, or `get_all_invoices` and format result. |
| `rag` | Knowledge base search | Retrieve relevant context chunks, generate answer, verify grounding. |
| `handoff` | Safety/escalation | Escalate to human support with clear handoff reason. |
| `respond` | General direct answer | Provide helpful direct natural-language response. |
