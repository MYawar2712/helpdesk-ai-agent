"""Persistent LangGraph checkpointers for the helpdesk application.

PostgreSQL is the production backend.  A file-backed SQLite saver is used for
local development and tests when the application database is SQLite, keeping
checkpoints separate from the business conversation/message tables.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_SQLITE_CHECKPOINT_PATH = (
    Path(__file__).resolve().parents[2] / "db" / "langgraph_checkpoints.sqlite3"
)

#: Low-level exception types that mean the checkpoint store itself is broken.
CHECKPOINT_STORAGE_ERRORS: tuple[type[BaseException], ...] = (
    sqlite3.Error,
    psycopg.Error,
    SQLAlchemyError,
)


class CheckpointUnavailableError(RuntimeError):
    """The persistent checkpoint store cannot be read or written.

    Raised for infrastructure problems (connection loss, corrupt/locked
    checkpoint database). Callers must surface this as a server-side error
    instead of silently starting a fresh conversation thread.
    """


class CheckpointStateError(RuntimeError):
    """The conversation cannot be safely resumed from persistent state.

    Raised when the thread identity requested by the caller does not match the
    thread the conversation resolves to, or when the stored state cannot be
    decoded. Never falls back to creating a second thread.
    """


def is_checkpoint_failure(exc: BaseException) -> bool:
    """Return True when *exc* originates from the checkpoint storage layer."""

    return isinstance(exc, CHECKPOINT_STORAGE_ERRORS)


def _sqlite_path_from_url(database_url: str) -> str:
    """Extract a filesystem path from a SQLAlchemy SQLite URL."""

    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("LANGGRAPH_DATABASE_URL must be a PostgreSQL or SQLite URL")
    path = database_url[len(prefix) :]
    if path in {"", ":memory:"}:
        return ":memory:"
    return path


def _postgres_url(database_url: str) -> str:
    """Normalize SQLAlchemy PostgreSQL URLs for the psycopg-backed saver."""

    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix) :]
    return database_url


def _configured_database_url() -> str | None:
    """Return the explicit checkpointer URL, then the application database URL."""

    return os.getenv("LANGGRAPH_DATABASE_URL") or os.getenv("DATABASE_URL") or None


def _setup_or_raise(saver: Any, backend: str) -> None:
    """Run the saver's idempotent setup, converting failures to a typed error.

    Only ``setup()`` is guarded. Exceptions raised by the *caller* inside the
    ``with open_persistent_checkpointer(...)`` block propagate untouched, so
    genuine application errors are never misreported as checkpoint failures.
    """

    try:
        saver.setup()
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed error
        raise CheckpointUnavailableError(
            f"Unable to initialize the {backend} checkpoint store."
        ) from exc


@contextmanager
def open_persistent_checkpointer(
    database_url: str | None = None,
) -> Iterator[Any]:
    """Open and initialize the configured persistent LangGraph checkpointer.

    ``LANGGRAPH_DATABASE_URL`` takes precedence over ``DATABASE_URL``.  When
    the application uses SQLite without an explicit checkpointer URL, a
    separate local checkpoint file is used so business message tables remain
    independent.  The yielded saver owns its connection for the lifetime of the
    context.
    """

    explicit_url = database_url is not None or bool(os.getenv("LANGGRAPH_DATABASE_URL"))
    configured_url = database_url or _configured_database_url()
    postgres_url = (
        _postgres_url(configured_url)
        if configured_url and not configured_url.startswith("sqlite")
        else None
    )

    if postgres_url:
        with PostgresSaver.from_conn_string(postgres_url) as saver:
            _setup_or_raise(saver, "PostgreSQL")
            yield saver
        return

    if configured_url and explicit_url:
        sqlite_path = _sqlite_path_from_url(configured_url)
    else:
        sqlite_path = os.getenv("LANGGRAPH_SQLITE_PATH") or str(
            DEFAULT_SQLITE_CHECKPOINT_PATH
        )

    if sqlite_path != ":memory:":
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    with SqliteSaver.from_conn_string(sqlite_path) as saver:
        _setup_or_raise(saver, "SQLite")
        yield saver
