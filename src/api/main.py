"""Application factory and lifecycle setup for the helpdesk API."""

# ruff: noqa: E402

from __future__ import annotations

import sqlite3
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# The repository uses top-level imports from ``src``. Add that directory when
# this module is launched through the documented ``src.api.main`` path.
SRC_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router
from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from ml.classifier import TicketClassifier

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize model and repository resources for the application lifetime."""

    app.state.classifier = TicketClassifier()
    sql_connection = sqlite3.connect("db/helpdesk.sqlite3", check_same_thread=False)
    transcript_connection = sqlite3.connect(
        "db/helpdesk.sqlite3", check_same_thread=False
    )
    app.state.repository = HelpdeskDataRepository(
        sql_connection, NoSQLClient(transcript_connection)
    )
    yield
    sql_connection.close()
    transcript_connection.close()


app = FastAPI(title="Helpdesk AI Agent", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a consistent JSON response for missing routes and records."""

    return JSONResponse(status_code=404, content={"detail": "Resource not found"})


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a safe response without exposing internal exception details."""

    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
