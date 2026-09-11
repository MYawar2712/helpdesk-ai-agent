# Day 8: Ticket classification

Day 8 introduces a local machine-learning pipeline for ticket triage. A
TF-IDF vectorizer and logistic-regression classifiers predict ticket category
and priority from the title and description.

The training workflow uses SQLite tickets when available and supplements them
with deterministic synthetic examples when the database is small. It reports
accuracy, weighted F1, and classification reports, then saves the models to
`models/ticket_classifier.joblib`.

`TicketClassifier` loads the artifact and returns category, priority, and a
confidence score. Predictions below `0.60` are flagged for LLM or human review.

Train the models with:

```powershell
python -m ml.train
```
