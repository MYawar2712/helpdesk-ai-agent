"""Unit tests for get_all_invoices tool."""

import sqlite3

import pytest

from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from tools.get_all_invoices import create_get_all_invoices_tool, get_all_invoices


def repository() -> HelpdeskDataRepository:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    return HelpdeskDataRepository(connection, NoSQLClient(sqlite3.connect(":memory:")))


def test_get_all_invoices_returns_both_paid_and_unpaid_invoices() -> None:
    repo = repository()
    result = get_all_invoices(repo, "customer-1")
    assert result["found"] is True
    statuses = {invoice["status"] for invoice in result["invoices"]}
    assert "paid" in statuses
    assert "unpaid" in statuses


def test_get_all_invoices_accepts_integer_customer_id() -> None:
    repo = repository()
    result = get_all_invoices(repo, "1")
    assert result["found"] is True
    assert len(result["invoices"]) == 2


def test_get_all_invoices_not_found() -> None:
    repo = repository()
    result = get_all_invoices(repo, "customer-999")
    assert result["found"] is False
    assert result["error"] == "Customer not found"


@pytest.mark.parametrize("identifier", ["", "  ", 123])
def test_invalid_customer_ids_are_rejected(identifier: object) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        get_all_invoices(repository(), identifier)  # type: ignore[arg-type]


def test_langchain_tool_exposes_typed_input() -> None:
    tool = create_get_all_invoices_tool(repository())
    assert tool.name == "get_all_invoices"
    assert "customer_id" in tool.args_schema.model_json_schema()["properties"]
