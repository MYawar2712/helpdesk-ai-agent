import sqlite3

from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database


def make_repository() -> HelpdeskDataRepository:
    sql_connection = sqlite3.connect(":memory:")
    seed_database(sql_connection)
    nosql_client = NoSQLClient(sqlite3.connect(":memory:"))
    return HelpdeskDataRepository(sql_connection, nosql_client)


def add_transcripts(repository: HelpdeskDataRepository) -> None:
    data = {
        "transcript_id": "transcript-context-1",
        "ticket_id": "ticket-1",
        "customer_id": "customer-1",
        "messages": [
            {
                "sender": "customer",
                "text": "The service is unavailable",
                "timestamp": "2026-01-15T10:00:00Z",
            }
        ],
        "metadata": {"device": "router", "channel": "chat", "duration": 120},
        "created_at": "2026-01-15T10:00:00Z",
    }
    repository.nosql_client.create_transcript(data)


def test_complete_ticket_context_combines_sql_and_nosql() -> None:
    repository = make_repository()
    add_transcripts(repository)

    context = repository.get_complete_ticket_context("ticket-1")

    assert context is not None
    assert context["ticket"]["id"] == "ticket-1"
    assert context["customer"]["id"] == "customer-1"
    assert len(context["jobs"]) == 2
    assert len(context["open_invoices"]) == 1
    assert context["transcripts"][0]["transcript_id"] == "transcript-context-1"


def test_customer_overview_combines_history_and_transcripts() -> None:
    repository = make_repository()
    add_transcripts(repository)

    overview = repository.get_customer_overview("customer-1")

    assert overview is not None
    assert overview["customer"]["name"] == "Ada Lovelace"
    assert len(overview["jobs"]) == 2
    assert len(overview["invoices"]) == 2
    assert len(overview["transcripts"]) == 1


def test_repository_returns_none_for_unknown_records() -> None:
    repository = make_repository()

    assert repository.get_complete_ticket_context("missing") is None
    assert repository.get_customer_overview("missing") is None
