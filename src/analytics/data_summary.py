"""Reusable analytical summaries for helpdesk data."""

from __future__ import annotations

from typing import TypedDict

import numpy as np
import pandas as pd


class FinancialSummary(TypedDict):
    """Financial metrics returned by :func:`financial_summary`."""

    total_overdue_revenue: float
    average_invoice_amount: float


def ticket_distribution(tickets: pd.DataFrame) -> pd.DataFrame:
    """Return ticket counts and overall percentages by category and priority."""

    required = {"category", "priority"}
    missing = required.difference(tickets.columns)
    if missing:
        raise ValueError(f"tickets is missing columns: {sorted(missing)}")
    result = (
        tickets.groupby(["category", "priority"], as_index=False)
        .size()
        .rename(columns={"size": "ticket_count"})
    )
    result["percentage"] = result["ticket_count"] / len(tickets) * 100
    return result


def financial_summary(invoices: pd.DataFrame) -> FinancialSummary:
    """Summarize overdue revenue and the mean value of all invoices."""

    required = {"amount", "status"}
    missing = required.difference(invoices.columns)
    if missing:
        raise ValueError(f"invoices is missing columns: {sorted(missing)}")
    overdue = invoices[invoices["status"].isin(["unpaid", "overdue"])]
    return {
        "total_overdue_revenue": float(overdue["amount"].sum()),
        "average_invoice_amount": float(np.mean(invoices["amount"])),
    }


def engineer_workload(jobs: pd.DataFrame) -> pd.DataFrame:
    """Return job totals, completion rates, and average resolution days."""

    required = {"assigned_engineer_id", "status", "created_at"}
    missing = required.difference(jobs.columns)
    if missing:
        raise ValueError(f"jobs is missing columns: {sorted(missing)}")
    working = jobs.copy()
    working["created_at"] = pd.to_datetime(working["created_at"])
    if "completed_at" in working:
        working["completed_at"] = pd.to_datetime(working["completed_at"])
        working["resolution_days"] = (
            working["completed_at"] - working["created_at"]
        ).dt.total_seconds() / 86400
    else:
        working["resolution_days"] = np.nan
    result = (
        working.dropna(subset=["assigned_engineer_id"])
        .groupby("assigned_engineer_id")
        .agg(
            total_jobs=("status", "size"),
            completed_jobs=("status", lambda values: (values == "completed").sum()),
            average_resolution_days=("resolution_days", "mean"),
        )
        .reset_index(names="engineer_id")
    )
    result["completion_rate"] = result["completed_jobs"] / result["total_jobs"] * 100
    return result[
        [
            "engineer_id",
            "total_jobs",
            "completed_jobs",
            "completion_rate",
            "average_resolution_days",
        ]
    ]


def high_ticket_volume_accounts(
    tickets: pd.DataFrame,
    customers: pd.DataFrame,
    invoices: pd.DataFrame,
) -> pd.DataFrame:
    """Find accounts with tickets and pending unpaid or overdue payments."""

    ticket_counts = (
        tickets.groupby("customer_id", as_index=False)
        .size()
        .rename(columns={"size": "ticket_count"})
    )
    pending = (
        invoices[invoices["status"].isin(["unpaid", "overdue"])]
        .groupby("customer_id", as_index=False)["amount"]
        .sum()
        .rename(columns={"amount": "pending_payment"})
    )
    return (
        ticket_counts.merge(
            customers[["id", "name"]], left_on="customer_id", right_on="id"
        )
        .drop(columns="id")
        .merge(pending, on="customer_id")
        .sort_values(["ticket_count", "pending_payment"], ascending=False)
        .reset_index(drop=True)
    )
