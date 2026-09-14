from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from tools.get_customer import get_customer
from tools.get_job import create_get_job_tool, get_job
from tools.get_open_invoices import get_open_invoices
from tools.tool_calling import ToolCallingAssistant


def repository() -> HelpdeskDataRepository:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    return HelpdeskDataRepository(connection, NoSQLClient(sqlite3.connect(":memory:")))


def test_get_job_returns_job_details() -> None:
    result = get_job(repository(), "job-1")

    assert result["found"] is True
    assert result["job"]["id"] == "job-1"


def test_get_customer_returns_customer_details() -> None:
    result = get_customer(repository(), "customer-1")

    assert result["found"] is True
    assert result["customer"]["name"] == "Ada Lovelace"
    assert "email" not in result["customer"]
    assert "phone" not in result["customer"]


def test_get_open_invoices_returns_unpaid_and_overdue_invoices() -> None:
    result = get_open_invoices(repository(), "customer-2")

    assert result["found"] is True
    assert [invoice["id"] for invoice in result["invoices"]] == [
        "invoice-7",
        "invoice-2",
    ]


def test_missing_record_returns_consistent_not_found_result() -> None:
    result = get_job(repository(), "missing")

    assert result == {"found": False, "job": None, "error": "Job not found"}


@pytest.mark.parametrize("identifier", ["", "  ", 123])
def test_invalid_ids_are_rejected(identifier: object) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        get_customer(repository(), identifier)  # type: ignore[arg-type]


def test_langchain_tool_exposes_typed_input_and_result_format() -> None:
    tool = create_get_job_tool(repository())

    assert tool.name == "get_job"
    assert "id" in tool.args_schema.model_json_schema()["properties"]
    assert tool.invoke({"id": "job-1"})["job"]["status"] == "completed"


def test_tool_calling_assistant_uses_result_for_final_response() -> None:
    data_repository = repository()
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="get_job", arguments='{"id": "job-1"}'),
    )
    selection = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tool_call])
            )
        ]
    )
    final = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="Job job-1 is completed."))
        ]
    )
    client = Mock()
    client.generate_with_tools.side_effect = [selection, final]
    assistant = ToolCallingAssistant(client, [create_get_job_tool(data_repository)])

    answer = assistant.answer("What is the status of job job-1?")

    assert answer == "Job job-1 is completed."
    follow_up_messages = client.generate_with_tools.call_args_list[1].args[0]
    tool_message = next(
        message for message in follow_up_messages if message["role"] == "tool"
    )
    assert json.loads(tool_message["content"])["job"]["id"] == "job-1"
