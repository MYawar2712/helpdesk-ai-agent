# Model evaluation notes

## Day 9 feature engineering and evaluation

For escalation prediction, start with ticket title and description. Useful
additional features include ML confidence, predicted priority, category, open
invoice balance, customer ticket count, and whether outage or financial-risk
keywords appear in the text.

Evaluate with a held-out test set and report:

- **Precision:** how many predicted escalations were true escalations.
- **Recall:** how many true escalations were detected.
- **F1:** the balance between precision and recall.
- **Confusion matrix:** the error pattern between escalation classes.

Accuracy alone can be misleading when most tickets are routine. Compare
logistic regression, linear SVM, and multinomial Naive Bayes using the same
split and preprocessing. For production, prefer a time-based split and track
false negatives carefully because missed urgent tickets are costly.
