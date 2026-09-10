import pandas as pd
import pytest

from analytics.data_summary import (
    engineer_workload,
    financial_summary,
    high_ticket_volume_accounts,
    ticket_distribution,
)


def test_ticket_distribution_counts_and_percentages() -> None:
    tickets = pd.DataFrame(
        {
            "customer_id": ["c1", "c1", "c2", "c2"],
            "category": ["billing", "billing", "access", "billing"],
            "priority": ["high", "low", "high", "high"],
        }
    )

    result = ticket_distribution(tickets)

    billing_high = result[(result.category == "billing") & (result.priority == "high")]
    assert billing_high.iloc[0].ticket_count == 2
    assert billing_high.iloc[0].percentage == 50.0


def test_financial_summary_uses_numpy_average_and_pending_statuses() -> None:
    invoices = pd.DataFrame(
        {"amount": [100.0, 200.0, 300.0], "status": ["paid", "unpaid", "overdue"]}
    )

    assert financial_summary(invoices) == {
        "total_overdue_revenue": 500.0,
        "average_invoice_amount": 200.0,
    }


def test_engineer_workload_calculates_completion_and_resolution() -> None:
    jobs = pd.DataFrame(
        {
            "assigned_engineer_id": ["e1", "e1", "e2"],
            "status": ["completed", "scheduled", "completed"],
            "created_at": ["2026-01-01"] * 3,
            "completed_at": ["2026-01-03", None, "2026-01-05"],
        }
    )

    result = engineer_workload(jobs).set_index("engineer_id")

    assert result.loc["e1", "total_jobs"] == 2
    assert result.loc["e1", "completion_rate"] == 50.0
    assert result.loc["e1", "average_resolution_days"] == 2.0
    assert result.loc["e2", "average_resolution_days"] == 4.0


def test_engineer_workload_handles_schema_without_completed_at() -> None:
    jobs = pd.DataFrame(
        {
            "assigned_engineer_id": ["e1"],
            "status": ["scheduled"],
            "created_at": ["2026-01-01"],
        }
    )

    result = engineer_workload(jobs)

    assert pd.isna(result.loc[0, "average_resolution_days"])


def test_high_ticket_volume_accounts_merges_pending_payments() -> None:
    tickets = pd.DataFrame(
        {"customer_id": ["c1", "c1", "c2"], "category": ["a", "b", "a"]}
    )
    customers = pd.DataFrame({"id": ["c1", "c2"], "name": ["Ada", "Grace"]})
    invoices = pd.DataFrame(
        {
            "customer_id": ["c1", "c1", "c2"],
            "amount": [100.0, 50.0, 200.0],
            "status": ["unpaid", "paid", "overdue"],
        }
    )

    result = high_ticket_volume_accounts(tickets, customers, invoices)

    assert result[["customer_id", "name", "ticket_count", "pending_payment"]].to_dict(
        "records"
    ) == [
        {
            "customer_id": "c1",
            "name": "Ada",
            "ticket_count": 2,
            "pending_payment": 100.0,
        },
        {
            "customer_id": "c2",
            "name": "Grace",
            "ticket_count": 1,
            "pending_payment": 200.0,
        },
    ]


@pytest.mark.parametrize(
    "function", [ticket_distribution, financial_summary, engineer_workload]
)
def test_summaries_reject_missing_columns(function) -> None:
    with pytest.raises(ValueError, match="missing columns"):
        function(pd.DataFrame())
