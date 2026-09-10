# Day 2: Typed domain models and tests

## What I implemented

Day 2 added the primary helpdesk domain entities in `src/models.py` using standard-library dataclasses:

- `Job` for scheduled customer work
- `Customer` for customer contact information
- `Invoice` for job charges and payment state
- `Ticket` for customer support requests

I also added the required enums: `JobStatus`, `TicketStatus`, `TicketPriority`, and `InvoiceStatus`. Every model field has an explicit type hint. The models validate required text fields, enum values, dates, datetimes, and invoice amounts at runtime.

Two useful domain properties were added:

- `Invoice.is_overdue` is true for explicitly overdue invoices or unpaid invoices past their due date.
- `Ticket.can_escalate` is true only for active high- or urgent-priority tickets.

## Tests

`tests/test_models.py` tests successful construction of all four models, optional job fields, enum validation, invalid values, invoice overdue calculations, ticket escalation rules, and negative invoice amounts. `pytest-cov` was added to `requirements.txt` so coverage can be measured locally.

The model tests completed successfully:

```text
11 passed
```

## Problems encountered and fixes

### Ruff failure

The first pre-commit run reported `E501` errors because several test lines were longer than the configured 88-character limit. Ruff also reported that its formatter had modified two files.

The fix was to run Ruff formatting and checks again:

```powershell
ruff format tests/test_models.py src/models.py
ruff check tests/test_models.py src/models.py
```

After formatting, Ruff reported:

```text
All checks passed!
```

### Pre-commit cache permission error

The code checks passed, but pre-commit could not write its cache database under `C:\Users\testu1\.cache\pre-commit`. The error was an environment permission problem, not a Python or model error.

Use a writable cache directory before running the hooks:

```powershell
$env:PRE_COMMIT_HOME = "$env:LOCALAPPDATA\pre-commit"
pre-commit run --all-files
```

### Staging reminder

Ruff can modify files. Those changes must be staged again before committing:

```powershell
git add src/models.py tests/test_models.py requirements.txt
git commit -m "Implement Day 2 domain models"
```
