# Day 9: Escalation and routing rules

Day 9 combines ML predictions with deterministic business rules in
`EscalationEngine`.

The engine evaluates confidence, priority, ticket text, and overdue invoice
balances. Low-confidence tickets go to `tier_1_manual_review`; urgent or
high-value tickets go to `vip_priority_queue`; financial disputes go to
`billing_specialists`. Other tickets use standard category queues.

Each decision returns an `EscalationResult` containing the destination queue,
escalation state, human-handoff flag, optional priority override, and readable
reasons for the decision.
