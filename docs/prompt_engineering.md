# Prompt engineering: ticket classification

Day 12 creates three equivalent ticket-classification prompts so their effect
can be evaluated later without changing the category vocabulary.

- **V1 role prompting** defines the classifier's role, task, categories, and
  output constraints. It provides a compact baseline.
- **V2 few-shot prompting** adds realistic examples to demonstrate how common
  customer requests map to categories. It may improve consistency but uses
  additional input tokens and can bias results toward the examples.
- **V3 structured/XML prompting** separates instructions into explicit role,
  task, category, input, and output sections. It is intended to make the
  instructions easier to parse and integrate, but adds formatting overhead.

The prompts are alternatives, not a ranking. Later evaluation should use the
same labelled ticket set, model, generation settings, and metrics for each
version, including accuracy, per-category F1, invalid-output rate, latency, and
token usage.
