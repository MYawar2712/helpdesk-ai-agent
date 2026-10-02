"""Thread-safe access to the legacy helpdesk SQLite store.

The legacy helpdesk tables predate the SQLAlchemy/PostgreSQL layer and are still
served through a single ``sqlite3.Connection`` created in the application
lifespan. That connection is created with ``check_same_thread=False`` so
FastAPI's thread pool can reach it, but a ``sqlite3.Connection`` is not safe to
share across threads: concurrent ``execute`` and ``commit`` calls interleave, so
one request can commit another request's half-finished transaction, and a
cursor can be reused mid-iteration.

Rather than change every call site, the connection is wrapped once and every
operation is serialised behind a re-entrant lock. SQLite serialises writes
internally anyway, so this removes the correctness problem without changing
behaviour. The SQLAlchemy/PostgreSQL layer used for tenants, agents, approvals
and audit logs is pooled separately and is not affected.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any


class SerializedSQLiteConnection:
    """A ``sqlite3.Connection`` proxy that serialises access across threads.

    Attribute access is forwarded to the wrapped connection, so existing callers
    (``connection.execute(...)``, ``connection.row_factory = ...``) keep working
    unchanged.
    """

    __slots__ = ("_connection", "_lock", "_closed")

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = threading.RLock()
        self._closed = False

    # ── Serialised operations ────────────────────────────────────────────

    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(*args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.executemany(*args, **kwargs)

    def executescript(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.executescript(*args, **kwargs)

    def cursor(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.cursor(*args, **kwargs)

    def commit(self) -> None:
        with self._lock:
            self._connection.commit()

    def rollback(self) -> None:
        with self._lock:
            self._connection.rollback()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._connection.close()

    # ── Passthrough ──────────────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        with self._lock:
            return getattr(self._connection, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in SerializedSQLiteConnection.__slots__:
            object.__setattr__(self, name, value)
            return
        with self._lock:
            setattr(self._connection, name, value)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SerializedSQLiteConnection closed={self._closed}>"


def serialize_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Return a thread-safe view of *connection*.

    Already-wrapped connections are returned unchanged so repeated wrapping
    (for example in tests that rebuild the repository) is harmless.
    """

    if isinstance(connection, SerializedSQLiteConnection):
        return connection
    return SerializedSQLiteConnection(connection)  # type: ignore[return-value]
