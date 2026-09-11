from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from db.seed import seed_database
from workers.celery_app import celery_app
from workers.tasks import process_ticket_async


def test_process_ticket_task_in_eager_mode(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "helpdesk.sqlite3"
    import sqlite3

    connection = sqlite3.connect(database)
    seed_database(connection)
    connection.close()
    monkeypatch.setattr("workers.tasks.DATABASE_PATH", database)
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)

    result = process_ticket_async.delay("ticket-1")

    assert result.get()["ticket_id"] == "ticket-1"
    check = sqlite3.connect(database)
    assert (
        check.execute("SELECT status FROM tickets WHERE id = 'ticket-1'").fetchone()[0]
        == "processed"
    )
    check.close()


def test_async_process_endpoint_returns_accepted() -> None:
    celery_app.conf.update(task_always_eager=True)
    with TestClient(app) as client:
        response = client.post("/api/v1/tickets/ticket-1/process-async")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["task_id"]
