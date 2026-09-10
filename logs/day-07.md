# Day 7: Week 1 summary

## Built

- Typed domain models and tests
- HTTP client with Pydantic validation and retries
- SQLite relational schema, seed data, and SQL queries
- Pandas/NumPy analytics and exploration notebook
- SQLite JSON transcript storage with CRUD and keyword search
- Unified `HelpdeskDataRepository` for SQL plus transcript context

## Architecture

The relational database remains the source for customers, tickets, jobs, and invoices. SQLite JSON stores unstructured transcripts. The data repository combines both stores into ticket and customer context payloads for future agent workflows.

## Challenges and decisions

The project used SQLite and in-memory tests to stay reproducible and offline. Strict Pydantic validation caught timestamp and JSON-shape issues early. The current schema links jobs to customers, not tickets, so ticket context returns the customer’s related jobs rather than guessing a direct job relationship.

## Week 2 focus

Add an explicit ticket-to-job relationship, improve transaction/error handling, remove local cache permission warnings, and add service-layer APIs above the repository.
