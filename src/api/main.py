"""Application factory and lifecycle setup for the helpdesk API."""

# ruff: noqa: E402

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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

from agent.checkpointer import open_persistent_checkpointer
from agent.graph import HelpdeskAgent
from agents.config import AgentConfigService, SQLAlchemyConfigStore
from agents.orchestrator import MultiAgentHelpdesk
from api.ai_config import router as ai_config_router
from api.approvals import router as approvals_router
from api.audit_logs import router as audit_logs_router
from api.auth import router as auth_router
from api.chat import router as chat_router
from api.customers import router as customers_router
from api.dashboard import router as dashboard_router
from api.engineers import router as engineers_router
from api.invoices import router as invoices_router
from api.jobs import router as jobs_router
from api.knowledge import router as knowledge_router
from api.routes import router
from api.tickets import router as tickets_router
from api.users import router as users_router
from clients.nosql_client import NoSQLClient
from core.config import get_settings
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from hitl.graph_gate import ApprovalGate
from llm.client import LLMClient
from ml.classifier import TicketClassifier
from rag.retrieval import TenantKnowledgeRetriever
from tools.cancel_job import create_cancel_job_tool
from tools.get_all_invoices import create_get_all_invoices_tool
from tools.get_customer import create_get_customer_tool
from tools.get_job import create_get_job_tool
from tools.get_open_invoices import create_get_open_invoices_tool
from tools.schedule_job import create_schedule_job_tool
from tools.update_job_status import create_update_job_status_tool

VERSION = "0.1.0"

logger = logging.getLogger(__name__)

#: Platform tool ceiling per agent. A tenant's ``allowed_tools`` list is
#: intersected with this, so tenant configuration can only narrow permissions.
PLATFORM_TOOL_SCOPE: dict[str, set[str]] = {
    "SUPPORT_AGENT": {
        "search_knowledge",
        "get_support_information",
        "get_job",
        "get_customer_jobs",
        "get_customer_invoices",
        "get_invoice",
        "get_engineers",
    },
    "JOB_AGENT": {
        "get_job",
        "get_customer_jobs",
        "create_job",
        "update_job_status",
        "reschedule_job",
        "cancel_job",
        "assign_engineer",
        "get_engineers",
    },
    "INVOICE_AGENT": {
        "get_invoice",
        "get_customer_invoices",
        "create_invoice",
        "update_invoice",
    },
    "TRIAGE": {"find_active_ticket", "create_ticket", "update_ticket"},
}


def _config_service_factory() -> AgentConfigService:
    """Build a per-turn configuration loader backed by a short-lived session.

    A fresh service per turn keeps the resolved-configuration cache scoped to a
    single agent execution (Day 8 §20) while never holding a stale long-lived
    database session.
    """

    from db.session import _SessionLocal

    session = _SessionLocal()
    return AgentConfigService(
        SQLAlchemyConfigStore(session),
        platform_tool_scope=PLATFORM_TOOL_SCOPE,
    )


def _chunk_source_factory() -> Any:
    """Return a tenant-scoped chunk source backed by a short-lived session."""

    from db.session import _SessionLocal
    from rag.documents import RelationalChunkSource

    return RelationalChunkSource(_SessionLocal())


def _tenant_vector_store() -> Any:
    """Build the shared tenant vector store, or ``None`` without an API key."""

    try:
        from rag.ingest import create_embedding_model
        from rag.tenant_store import TenantVectorStore

        return TenantVectorStore(embeddings=create_embedding_model())
    except Exception:  # noqa: BLE001 - retrieval falls back to keyword search
        return None


def _approval_session_factory() -> Any:
    """Return a short-lived session for the Day 9 approval workflow."""

    from db.session import _SessionLocal

    return _SessionLocal()


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

    # The same serialised view the repository exposes, so the conversation
    # repository cannot race the agent tools on one shared SQLite connection.
    conv_repo = ConversationRepository(repo.sql_connection)
    app.state.conv_repository = conv_repo
    with open_persistent_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer
        # Day 6 single-agent graph, retained as the fallback for unauthenticated
        # requests that carry no customer identity.
        base_agent = HelpdeskAgent(
            conversation_repo=conv_repo,
            checkpointer=checkpointer,
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
        # Day 8: tenant configuration loader and tenant-isolated retriever.
        # A fresh config service is built per turn; the tenant retriever is
        # bound to the application's SQLAlchemy session factory.
        app.state.tenant_vector_store = _tenant_vector_store()
        app.state.tenant_retriever = TenantKnowledgeRetriever(
            vector_store=app.state.tenant_vector_store,
            source_factory=_chunk_source_factory,
        )
        # Day 9: the approval gate needs a session factory to persist requests
        # and to guard execution with a single atomic claim.
        app.state.approval_gate = ApprovalGate(
            session_factory=_approval_session_factory,
            enable_interrupt=checkpointer is not None,
        )
        app.state.multi_agent = MultiAgentHelpdesk.create(
            repository=repo,
            llm=LLMClient(),
            checkpointer=checkpointer,
            fallback=base_agent,
            config_service_factory=_config_service_factory,
            tenant_retriever=app.state.tenant_retriever,
            approval_gate=app.state.approval_gate,
        )
        app.state.agent = app.state.multi_agent
        try:
            yield
        finally:
            app.state.checkpointer = None
            app.state.multi_agent = None
            sql_connection.close()
            transcript_connection.close()


app = FastAPI(title="Helpdesk AI Agent", version=VERSION, lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parents[2] / "static")),
    name="static",
)

# Origins come from configuration. A wildcard is rejected by the Settings
# validator: with credentials allowed, ``*`` would let any website act as a
# signed-in user. Credentials stay enabled so the API can be used from a
# browser session without weakening the origin check.
_cors_origins = list(get_settings().cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
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
app.include_router(chat_router)
app.include_router(ai_config_router)
app.include_router(knowledge_router)
app.include_router(approvals_router)
app.include_router(audit_logs_router)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a consistent JSON response for missing routes and records."""
    return JSONResponse(status_code=404, content={"detail": "Resource not found"})


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a safe response without exposing internal exception details.

    The detail is deliberately a fixed string. Interpolating ``exc`` here would
    forward connection strings, SQL fragments, file paths, and prompt text to
    the caller; the traceback belongs in the server log only.
    """

    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so an unexpected failure never leaks its message to a client."""

    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
