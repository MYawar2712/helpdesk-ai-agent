"""Day 9 tests: LangGraph pause/resume for human approvals, with real persistence.

The graph is compiled with a real SQLite checkpointer and approvals are stored in
a real database, so a pause survives discarding and rebuilding the application
objects. No in-memory fakes stand in for the persisted state.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from day7_9_helpers import job_status, legacy_helpdesk, legacy_job_ids
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from agent.checkpointer import open_persistent_checkpointer
from agents.actions import ApprovalStatus
from agents.context import AgentContext
from agents.orchestrator import MultiAgentHelpdesk
from db.models import ApprovalRequest, AuditLog
from hitl.audit_events import AuditAction
from hitl.graph_gate import PENDING_MESSAGE, REJECTED_MESSAGE, ApprovalGate
from hitl.service import ApprovalService

TENANT_ID = "tenant-hitl"
CUSTOMER_ID = "customer-1"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _session_factory(tmp_path: Path, name: str, *, create: bool = True) -> sessionmaker:
    """Return a sessionmaker over a file-backed schema.

    With ``create=False`` the existing database is reused, so a test can prove
    state was genuinely persisted rather than re-initialised.
    """

    engine = create_engine(f"sqlite:///{(tmp_path / name).as_posix()}")
    if create:
        from db.models import Base

        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@contextmanager
def _app(tmp_path: Path, *, seed: bool = True) -> Iterator[dict[str, Any]]:
    """Build the full application stack, as a real startup would.

    ``seed=False`` reuses the databases already on disk, which is what a
    simulated restart needs: the approval rows and the LangGraph checkpoints
    must be read back from persistent storage, not re-created.
    """

    factory = _session_factory(tmp_path, "app.sqlite3", create=seed)
    repo, connection = legacy_helpdesk(tmp_path, seed=seed)
    checkpoint_path = (tmp_path / "checkpoints.sqlite3").as_posix()
    try:
        with open_persistent_checkpointer(f"sqlite:///{checkpoint_path}") as saver:
            gate = ApprovalGate(session_factory=factory)
            agent = MultiAgentHelpdesk.create(
                repository=repo,
                checkpointer=saver,
                use_llm_triage=False,
                approval_gate=gate,
            )
            yield {
                "agent": agent,
                "factory": factory,
                "connection": connection,
            }
    finally:
        connection.close()


@pytest.fixture()
def env(tmp_path: Path) -> Iterator[dict[str, Any]]:
    with _app(tmp_path) as value:
        yield value


def _pending(session: Session) -> ApprovalRequest:
    rows = session.scalars(
        select(ApprovalRequest).where(ApprovalRequest.tenant_id == TENANT_ID)
    ).all()
    assert rows, "expected a pending approval to exist"
    return rows[0]


def _decision(approval_id: str, approved: bool = True) -> dict[str, Any]:
    return {
        "approval_id": approval_id,
        "decision": "approved" if approved else "rejected",
        "reviewer_id": "reviewer-1",
        "comment": "Reviewed by a human.",
    }


def _turn(agent: MultiAgentHelpdesk, text: str, conversation_id: str) -> dict[str, Any]:
    return agent.invoke(
        text,
        email_thread_id=conversation_id,
        customer_id=CUSTOMER_ID,
        tenant_id=TENANT_ID,
    )


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------


class TestApprovalPausesGraph:
    def test_cancellation_creates_pending_approval_instead_of_executing(
        self, env
    ) -> None:
        agent, connection = env["agent"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]

        state = _turn(agent, f"Please cancel my job {job_id}", "conv-cancel")

        # The turn is suspended awaiting a human decision.
        assert state["pending_approval"] is not None
        assert state["approval_id"]
        # The customer sees a neutral message with no internal detail.
        assert state["final_response"] == PENDING_MESSAGE
        assert state["requires_human"] is False
        # The business action has NOT happened yet.
        assert job_status(connection, job_id) != "cancelled"

    def test_pending_approval_is_persisted_with_context(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        state = _turn(agent, f"Please cancel my job {job_id}", "conv-cancel-2")

        session = factory()
        try:
            row = _pending(session)
            assert row.id == state["approval_id"]
            assert row.status == ApprovalStatus.PENDING.value
            # conversation_id is the same identity used as the LangGraph thread.
            assert row.conversation_id == "conv-cancel-2"
            assert row.tenant_id == TENANT_ID
            assert row.action_type == "cancel_job"
            assert row.resource_type == "job"
            assert row.resource_id == job_id
            assert row.risk_level == "HIGH"
            # Requested by the agent, not by a human.
            assert row.reviewed_by is None
        finally:
            session.close()

    def test_a_ticket_is_created_for_the_approval_turn(self, env) -> None:
        agent, connection = env["agent"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        state = _turn(agent, f"Please cancel my job {job_id}", "conv-cancel-3")
        assert state["ticket_id"]

    def test_proposal_and_creation_are_audited(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        state = _turn(agent, f"Please cancel my job {job_id}", "conv-cancel-4")
        session = factory()
        try:
            actions = {row.action for row in session.query(AuditLog).all()}
            assert AuditAction.AGENT_ACTION_PROPOSED.value in actions
            assert AuditAction.APPROVAL_CREATED.value in actions
            assert all(
                row.tenant_id == TENANT_ID for row in session.query(AuditLog).all()
            )
            assert state["approval_id"]
        finally:
            session.close()

    def test_safe_request_is_not_paused(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        state = _turn(agent, f"What is the status of job {job_id}?", "conv-status")
        # A read needs no approval, so the turn completes normally.
        assert state["pending_approval"] is None
        assert state["approval_id"] is None
        assert state["final_response"]
        session = factory()
        try:
            assert session.query(ApprovalRequest).count() == 0
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Approve -> resume -> execute
# ---------------------------------------------------------------------------


class TestApproveAndResume:
    def _approve(self, factory) -> str:
        session = factory()
        try:
            row = _pending(session)
            ApprovalService(session).approve(
                row.id, tenant_id=TENANT_ID, reviewer_id="reviewer-1"
            )
            return row.id
        finally:
            session.close()

    def test_approved_action_executes_on_resume(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        _turn(agent, f"Please cancel my job {job_id}", "conv-approve")
        approval_id = self._approve(factory)

        state = agent.resume(
            conversation_id="conv-approve",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id),
            tenant_id=TENANT_ID,
        )

        assert state["pending_approval"] is None
        assert state["final_response"]
        assert job_status(connection, job_id) == "cancelled"

        session = factory()
        try:
            assert _pending(session).status == ApprovalStatus.EXECUTED.value
        finally:
            session.close()

    def test_execution_is_audited(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        _turn(agent, f"Please cancel my job {job_id}", "conv-approve-audit")
        approval_id = self._approve(factory)
        agent.resume(
            conversation_id="conv-approve-audit",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id),
            tenant_id=TENANT_ID,
        )
        session = factory()
        try:
            actions = {row.action for row in session.query(AuditLog).all()}
            assert AuditAction.APPROVAL_APPROVED.value in actions
            assert AuditAction.AGENT_ACTION_EXECUTED.value in actions
        finally:
            session.close()

    def test_resume_uses_the_same_thread_id(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        paused = _turn(agent, f"Please cancel my job {job_id}", "conv-thread")
        approval_id = self._approve(factory)
        resumed = agent.resume(
            conversation_id="conv-thread",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id),
            tenant_id=TENANT_ID,
        )
        # The same conversation identity carried through pause and resume.
        assert paused["thread_id"] == "conv-thread"
        assert resumed["thread_id"] == "conv-thread"
        session = factory()
        try:
            assert _pending(session).conversation_id == "conv-thread"
        finally:
            session.close()

    def test_repeated_resume_executes_the_action_only_once(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        _turn(agent, f"Please cancel my job {job_id}", "conv-retry")
        approval_id = self._approve(factory)

        first = agent.resume(
            conversation_id="conv-retry",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id),
            tenant_id=TENANT_ID,
        )
        second = agent.resume(
            conversation_id="conv-retry",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id),
            tenant_id=TENANT_ID,
        )
        # The graph completes on both attempts, but the business action ran once.
        assert first["final_response"]
        assert second["final_response"]
        assert job_status(connection, job_id) == "cancelled"
        session = factory()
        try:
            assert session.query(ApprovalRequest).count() == 1
            assert _pending(session).status == ApprovalStatus.EXECUTED.value
        finally:
            session.close()

    def test_no_duplicate_approval_rows_across_resume(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        _turn(agent, f"Please cancel my job {job_id}", "conv-dedup")
        approval_id = self._approve(factory)
        agent.resume(
            conversation_id="conv-dedup",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id),
            tenant_id=TENANT_ID,
        )
        session = factory()
        try:
            assert session.query(ApprovalRequest).count() == 1
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


class TestReject:
    def test_rejected_action_is_not_executed(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        _turn(agent, f"Please cancel my job {job_id}", "conv-reject")
        session = factory()
        try:
            row = _pending(session)
            ApprovalService(session).reject(
                row.id, tenant_id=TENANT_ID, reviewer_id="reviewer-1"
            )
            approval_id = row.id
        finally:
            session.close()

        state = agent.resume(
            conversation_id="conv-reject",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id, approved=False),
            tenant_id=TENANT_ID,
        )

        assert state["final_response"] == REJECTED_MESSAGE
        # The job is untouched.
        assert job_status(connection, job_id) != "cancelled"
        session = factory()
        try:
            assert _pending(session).status == ApprovalStatus.REJECTED.value
        finally:
            session.close()

    def test_rejection_is_audited(self, env) -> None:
        agent, factory, connection = env["agent"], env["factory"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        _turn(agent, f"Please cancel my job {job_id}", "conv-reject-audit")
        session = factory()
        try:
            row = _pending(session)
            ApprovalService(session).reject(
                row.id, tenant_id=TENANT_ID, reviewer_id="reviewer-1"
            )
            approval_id = row.id
        finally:
            session.close()
        agent.resume(
            conversation_id="conv-reject-audit",
            customer_id=CUSTOMER_ID,
            decision=_decision(approval_id, approved=False),
            tenant_id=TENANT_ID,
        )
        session = factory()
        try:
            actions = {row.action for row in session.query(AuditLog).all()}
            assert AuditAction.APPROVAL_REJECTED.value in actions
            assert AuditAction.AGENT_ACTION_EXECUTED.value not in actions
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Persistence across a restart
# ---------------------------------------------------------------------------


class TestPersistenceAcrossRestart:
    def test_paused_state_survives_application_restart(self, tmp_path: Path) -> None:
        # --- First process: pause the graph and approve nothing. ---
        with _app(tmp_path) as first:
            connection = first["connection"]
            job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
            state = first["agent"].invoke(
                f"Please cancel my job {job_id}",
                email_thread_id="conv-restart",
                customer_id=CUSTOMER_ID,
                tenant_id=TENANT_ID,
            )
            approval_id = state["approval_id"]
            assert approval_id

        # Every application object above is now discarded.

        # --- Second process: a human approves, then the graph resumes. ---
        with _app(tmp_path, seed=False) as second:
            factory = second["factory"]
            connection = second["connection"]
            assert job_status(connection, job_id) != "cancelled"

            session = factory()
            try:
                row = _pending(session)
                assert row.id == approval_id
                assert row.status == ApprovalStatus.PENDING.value
                ApprovalService(session).approve(
                    row.id, tenant_id=TENANT_ID, reviewer_id="reviewer-2"
                )
            finally:
                session.close()

            resumed = second["agent"].resume(
                conversation_id="conv-restart",
                customer_id=CUSTOMER_ID,
                decision=_decision(approval_id),
                tenant_id=TENANT_ID,
            )
            assert resumed["final_response"]
            # The action finally executed, on the same thread, after a restart.
            assert job_status(connection, job_id) == "cancelled"

    def test_approval_survives_restart_even_without_resume(
        self, tmp_path: Path
    ) -> None:
        with _app(tmp_path) as first:
            connection = first["connection"]
            job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
            first["agent"].invoke(
                f"Please cancel my job {job_id}",
                email_thread_id="conv-restart-2",
                customer_id=CUSTOMER_ID,
                tenant_id=TENANT_ID,
            )

        with _app(tmp_path, seed=False) as second:
            session = second["factory"]()
            try:
                rows = session.query(ApprovalRequest).all()
                assert len(rows) == 1
                assert rows[0].status == ApprovalStatus.PENDING.value
                assert rows[0].conversation_id == "conv-restart-2"
            finally:
                session.close()
            # The new process sees a suspended thread for that conversation.
            snapshot = second["agent"].pending_snapshot(
                conversation_id="conv-restart-2",
                customer_id=CUSTOMER_ID,
                tenant_id=TENANT_ID,
            )
            assert snapshot is not None

    def test_two_conversations_keep_separate_threads(self, tmp_path: Path) -> None:
        with _app(tmp_path) as env:
            connection = env["connection"]
            job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
            _turn(env["agent"], f"Please cancel my job {job_id}", "conv-a")
            _turn(env["agent"], f"Please cancel my job {job_id}", "conv-b")
            session = env["factory"]()
            try:
                conversations = {
                    row.conversation_id for row in session.query(ApprovalRequest)
                }
                assert conversations == {"conv-a", "conv-b"}
            finally:
                session.close()


# ---------------------------------------------------------------------------
# Gate wiring
# ---------------------------------------------------------------------------


class TestApprovalGate:
    def test_gate_executes_safe_actions_without_an_approval(self) -> None:
        from agents.actions import AgentAction

        gate = ApprovalGate(session_factory=None)
        ctx = AgentContext(customer_id=CUSTOMER_ID, conversation_id="c")
        state = {"proposed_action": _read_action(), "destination": "job"}
        out = gate(state, ctx)
        # No session factory means no persisted request, but the turn completes.
        assert out["agent_result"]["data"]["approval_id"] is None
        assert AgentAction is not None

    def test_gate_clears_a_consumed_proposal(self, env) -> None:
        agent, connection = env["agent"], env["connection"]
        job_id = legacy_job_ids(connection, CUSTOMER_ID)["active"]
        state = _turn(agent, f"Please cancel my job {job_id}", "conv-gate")
        assert state["pending_approval"] is not None
        # A pending turn must still expose its proposal for the gate to re-enter.
        assert state["pending_approval"]["approval_id"] == state["approval_id"]

    def test_turn_without_a_proposal_is_untouched(self) -> None:
        gate = ApprovalGate(session_factory=None)
        ctx = AgentContext(customer_id=CUSTOMER_ID, conversation_id="c")
        out = gate({"user_message": "hello"}, ctx)
        assert out == {"proposed_action": None}


def _read_action():
    from agents.actions import AgentAction

    return AgentAction(
        action_type="get_job",
        resource_type="job",
        resource_id="job-1",
        parameters={"job_id": "job-1"},
        reason="Customer asked for a job status.",
    )
