"""SQLAlchemy session factory for the authentication layer.

This module provides a lightweight session factory that uses the ``database_url``
from Settings.  Existing SQLite-based infrastructure (``HelpdeskDataRepository``,
seed scripts) is unchanged – this session is only used by auth endpoints that
need to read/write the ``users`` and ``tenants`` tables via SQLAlchemy ORM.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


def _build_engine():  # type: ignore[return]
    """Build a SQLAlchemy engine from the current settings."""
    settings = get_settings()
    url = settings.database_url

    # SQLite needs check_same_thread=False for FastAPI's threaded test client.
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    return create_engine(url, connect_args=connect_args, echo=settings.debug)


# Module-level engine and factory – created once when this module is imported.
_engine = _build_engine()
_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


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
