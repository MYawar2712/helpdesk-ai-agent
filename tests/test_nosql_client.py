import sqlite3

import pytest

from clients.nosql_client import NoSQLClient, TranscriptValidationError


def transcript_data() -> dict:
    return {
        "transcript_id": "transcript-1",
        "ticket_id": "ticket-1",
        "customer_id": "customer-1",
        "messages": [
            {
                "sender": "customer",
                "text": "The router is offline",
                "timestamp": "2026-01-15T10:00:00Z",
            },
            {
                "sender": "agent",
                "text": "I will check the connection",
                "timestamp": "2026-01-15T10:01:00Z",
            },
        ],
        "metadata": {"device": "router-7", "channel": "chat", "duration": 180},
        "created_at": "2026-01-15T10:00:00Z",
    }


@pytest.fixture
def client() -> NoSQLClient:
    connection = sqlite3.connect(":memory:")
    return NoSQLClient(connection)


def test_create_and_get_transcript(client: NoSQLClient) -> None:
    transcript_id = client.create_transcript(transcript_data())

    result = client.get_transcript(transcript_id)

    assert result is not None
    assert result["customer_id"] == "customer-1"
    assert result["messages"][0]["text"] == "The router is offline"


def test_optional_ticket_id_and_strict_validation(client: NoSQLClient) -> None:
    data = transcript_data()
    data.pop("ticket_id")

    assert client.create_transcript(data) == "transcript-1"
    assert client.get_transcript("transcript-1")["ticket_id"] is None

    invalid = transcript_data()
    invalid["metadata"]["duration"] = "180"
    with pytest.raises(TranscriptValidationError):
        client.create_transcript(invalid)


def test_update_nested_metadata(client: NoSQLClient) -> None:
    client.create_transcript(transcript_data())

    assert client.update_transcript_metadata(
        "transcript-1", {"device": "mobile", "channel": "phone", "duration": 240}
    )
    assert client.get_transcript("transcript-1")["metadata"] == {
        "device": "mobile",
        "channel": "phone",
        "duration": 240,
    }
    assert (
        client.update_transcript_metadata(
            "missing", {"device": "phone", "channel": "chat", "duration": 1}
        )
        is False
    )


def test_keyword_search_is_case_insensitive(client: NoSQLClient) -> None:
    first = transcript_data()
    second = transcript_data()
    second["transcript_id"] = "transcript-2"
    second["messages"][0]["text"] = "Billing question about an invoice"
    client.create_transcript(first)
    client.create_transcript(second)

    results = client.search_transcripts_by_keyword("ROUTER")

    assert [item["transcript_id"] for item in results] == ["transcript-1"]
    with pytest.raises(ValueError, match="keyword"):
        client.search_transcripts_by_keyword(" ")


def test_delete_transcript(client: NoSQLClient) -> None:
    client.create_transcript(transcript_data())

    assert client.delete_transcript("transcript-1") is True
    assert client.get_transcript("transcript-1") is None
    assert client.delete_transcript("transcript-1") is False


def test_database_stores_valid_json(client: NoSQLClient) -> None:
    client.create_transcript(transcript_data())

    result = client.connection.execute(
        "SELECT json_valid(document), created_at FROM transcripts"
    ).fetchone()

    assert result[0] == 1
    assert result[1].startswith("2026-01-15")
