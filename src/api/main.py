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

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.graph import HelpdeskAgent
from api.auth import router as auth_router
from api.customers import router as customers_router
from api.dashboard import router as dashboard_router
from api.engineers import router as engineers_router
from api.invoices import router as invoices_router
from api.jobs import router as jobs_router
from api.routes import router
from api.tickets import router as tickets_router
from api.users import router as users_router
from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from ml.classifier import TicketClassifier
from tools.cancel_job import create_cancel_job_tool
from tools.get_all_invoices import create_get_all_invoices_tool
from tools.get_customer import create_get_customer_tool
from tools.get_job import create_get_job_tool
from tools.get_open_invoices import create_get_open_invoices_tool
from tools.schedule_job import create_schedule_job_tool
from tools.update_job_status import create_update_job_status_tool

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize model and repository resources for application lifetime."""
    app.state.classifier = TicketClassifier()
    sql_connection = sqlite3.connect("db/helpdesk.sqlite3", check_same_thread=False)
    seed_database(sql_connection)
    transcript_connection = sqlite3.connect(
        "db/helpdesk.sqlite3", check_same_thread=False
    )
    repo = HelpdeskDataRepository(sql_connection, NoSQLClient(transcript_connection))
    app.state.repository = repo
    from db.conversation_repository import ConversationRepository

    conv_repo = ConversationRepository(sql_connection)
    app.state.conv_repository = conv_repo
    app.state.agent = HelpdeskAgent(
        conversation_repo=conv_repo,
        tools=[
            create_get_job_tool(repo),
            create_get_customer_tool(repo),
            create_get_open_invoices_tool(repo),
            create_get_all_invoices_tool(repo),
            create_schedule_job_tool(),
            create_cancel_job_tool(repo),
            create_update_job_status_tool(repo),
        ],
    )
    yield
    sql_connection.close()
    transcript_connection.close()


app = FastAPI(title="Helpdesk AI Agent", version=VERSION, lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parents[2] / "static")),
    name="static",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(dashboard_router)
app.include_router(tickets_router)
app.include_router(jobs_router)
app.include_router(customers_router)
app.include_router(engineers_router)
app.include_router(invoices_router)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a consistent JSON response for missing routes and records."""
    return JSONResponse(status_code=404, content={"detail": "Resource not found"})


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a safe response without exposing internal exception details."""
    detail_msg = getattr(exc, "detail", None) or "Internal server error"
    return JSONResponse(status_code=500, content={"detail": detail_msg})
