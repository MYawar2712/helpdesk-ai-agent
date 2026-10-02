"""SQLAlchemy session factory for the authentication layer.

This module provides a lightweight session factory that uses the ``database_url``
from Settings.  Existing SQLite-based infrastructure (``HelpdeskDataRepository``,
seed scripts) is unchanged – this session is only used by auth endpoints that
need to read/write the ``users`` and ``tenants`` tables via SQLAlchemy ORM.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


def _build_engine():  # type: ignore[return]
    """Build a SQLAlchemy engine from the current settings.

    Pooling is configured explicitly so concurrent requests queue for a
    connection instead of opening an unbounded number of them. SQLite uses
    ``NullPool``-style single-file semantics via ``QueuePool`` defaults, which is
    fine for the local development database; PostgreSQL is the deployment target
    and gets an explicit bounded pool with pre-ping and recycling.
    """
    settings = get_settings()
    url = settings.database_url

    # SQLite needs check_same_thread=False for FastAPI's threaded test client.
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    if url.startswith("sqlite"):
        # A single shared file database cannot usefully hold more than one
        # writer; a small bounded pool plus a lock is handled by SQLite itself.
        return create_engine(
            url,
            connect_args=connect_args,
            echo=settings.debug,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
        )

    return create_engine(
        url,
        connect_args=connect_args,
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        # Recycle before a proxy or server drops an idle connection, and
        # validate on checkout so a stale connection never reaches a request.
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
    )


# Module-level engine and factory – created once when this module is imported.
_engine = _build_engine()
_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Yield a short-lived session that is always closed.

    Background helpers (tenant configuration loading, chunk-source retrieval,
    approval persistence) run outside a request. Creating a session per call
    without closing it leaks a pooled connection, so under concurrent load the
    pool is exhausted and every request starts failing. Always use this for
    work that is not driven by the ``get_db`` dependency.
    """

    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    Automatically closes the session after the request completes (or if an
    exception propagates through).  Use as::

        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """Create all ORM-mapped tables that do not yet exist.

    Intended for test fixtures and ``lifespan`` startup when Alembic is not
    being used (e.g. in-memory SQLite databases).  Has no effect if the tables
    already exist.
    """
    from db.models import Base

    Base.metadata.create_all(_engine)
