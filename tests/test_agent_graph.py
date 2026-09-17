from __future__ import annotations

import sqlite3
from unittest.mock import Mock

from agent.graph import HelpdeskAgent
from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from tools.get_job import create_get_job_tool
from tools.get_open_invoices import create_get_open_invoices_tool


def repository() -> HelpdeskDataRepository:
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    return HelpdeskDataRepository(connection, NoSQLClient(sqlite3.connect(":memory:")))


def test_respond_route_reaches_final_output() -> None:
    client = Mock()
    client.generate_json.return_value = {
        "route": "respond",
        "response": "I can answer this directly.",
    }
    agent = HelpdeskAgent(llm_client=client)

    result = agent.invoke("What are your opening hours?")

    assert result["final_response"] == "I can answer this directly."
    client.generate.assert_not_called()


def test_tool_route_runs_existing_database_tool_then_final_llm() -> None:
    client = Mock()
    client.generate_json.return_value = {
        "route": "tool",
        "tool_name": "get_job",
        "tool_input": {"id": "job-1"},
    }
    client.generate.return_value = "Job job-1 is completed."
    agent = HelpdeskAgent(
        llm_client=client,
        tools=[create_get_job_tool(repository())],
    )

    result = agent.invoke("What is the status of job job-1?")

    assert result["tool_result"]["job"]["id"] == "job-1"
    assert result["final_response"] == "Job job-1 is completed."
    client.generate.assert_called_once()


def test_tool_route_accepts_llm_job_id_alias() -> None:
    client = Mock()
    client.generate_json.return_value = {
        "route": "tool",
        "tool_name": "get_job",
        "tool_input": {"job_id": "job-1"},
    }
    client.generate.return_value = "Job job-1 is completed."
    agent = HelpdeskAgent(
        llm_client=client,
        tools=[create_get_job_tool(repository())],
    )

    result = agent.invoke("What is the status of job job-1?")

    assert result["tool_result"]["job"]["id"] == "job-1"
    assert result["final_response"] == "Job job-1 is completed."


def test_invoice_route_accepts_customer_number_and_id_alias() -> None:
    client = Mock()
    client.generate_json.return_value = {
        "route": "tool",
        "tool_name": "get_open_invoices",
        "tool_input": {"id": "1"},
    }
    client.generate.return_value = "Customer 1 has one open invoice."
    agent = HelpdeskAgent(
        llm_client=client,
        tools=[create_get_open_invoices_tool(repository())],
    )

    result = agent.invoke("Give me the invoices of customer 1.")

    assert result["tool_result"]["found"] is True
    assert result["tool_result"]["invoices"]
    assert result["final_response"] == "Customer 1 has one open invoice."


def test_decision_accepts_tool_key_without_explicit_route() -> None:
    client = Mock()
    client.generate_json.return_value = {
        "tool": "get_open_invoices",
        "tool_input": {"customer_id": "customer-1"},
    }
    client.generate.return_value = "Customer 1 has open invoices."
    agent = HelpdeskAgent(
        llm_client=client,
        tools=[create_get_open_invoices_tool(repository())],
    )

    result = agent.invoke("Give me the invoices of customer customer-1.")

    assert result["route"] == "tool"
    assert result["tool_result"]["found"] is True


def test_handoff_route_skips_tools_and_produces_human_message() -> None:
    client = Mock()
    client.generate_json.return_value = {
        "route": "handoff",
        "handoff_reason": "The customer reports a safety concern.",
    }
    agent = HelpdeskAgent(llm_client=client)

    result = agent.invoke("There is a dangerous electrical smell from the unit.")

    assert result["route"] == "handoff"
    assert "human support" in result["final_response"]
    assert "safety concern" in result["final_response"]
    client.generate.assert_not_called()


def test_dispute_keywords_force_handoff() -> None:
    client = Mock()
    agent = HelpdeskAgent(llm_client=client)

    result = agent.invoke("I have a billing issue got charged twice")

    assert result["route"] == "handoff"
    assert "human support" in result["final_response"].lower()
    client.generate_json.assert_not_called()
