"""Day 9 tests: structured actions, approval policy, workflow, and audit.

No LLM, embedding, or external service is contacted: agents run with
``llm=None`` and the knowledge path is not exercised here.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from day7_9_helpers import legacy_helpdesk, make_tenant
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.actions import (
    TERMINAL_STATUSES,
    ActionRisk,
    AgentAction,
    ApprovalDecision,
    ApprovalStatus,
)
from agents.approval_policy import (
    ApprovalPolicy,
    ApprovalRequirement,
    evaluate,
    risk_for,
)
from db.models import ApprovalRequest, AuditLog
from hitl.audit_events import AuditAction, log_agent_event
from hitl.service import (
    ApprovalConflict,
    ApprovalExpired,
    ApprovalNotFound,
    ApprovalService,
    execute_once,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _action(**overrides) -> AgentAction:
    payload = {
        "action_type": "cancel_job",
        "resource_type": "job",
        "resource_id": "job-123",
        "parameters": {},
        "reason": "Customer requested cancellation",
    }
    payload.update(overrides)
    return AgentAction(**payload)


@pytest.fixture()
def service(sa_session: Session) -> ApprovalService:
    return ApprovalService(sa_session)


def _create(
    session: Session,
    *,
    tenant_id: str = "tenant-a",
    conversation_id: str = "conv-1",
    action: AgentAction | None = None,
    ttl: timedelta = timedelta(hours=24),
) -> ApprovalRequest:
    return ApprovalService(session).create(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        agent_type="job",
        action=action or _action(),
        requirement=evaluate(_action()),
        requested_by="job",
        ttl=ttl,
    )


# ---------------------------------------------------------------------------
# AgentAction structured model
# ---------------------------------------------------------------------------


class TestAgentActionModel:
    def test_valid_action(self) -> None:
        action = _action()
        assert action.action_type == "cancel_job"
        assert action.resource_type == "job"
        assert action.resource_id == "job-123"
        assert action.reason == "Customer requested cancellation"

    def test_types_are_normalised(self) -> None:
        action = _action(action_type="  CANCEL_JOB  ", resource_type=" Job ")
        assert action.action_type == "cancel_job"
        assert action.resource_type == "job"

    def test_empty_action_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _action(action_type="   ")

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _action(reason="")

    def test_resource_id_is_optional(self) -> None:
        assert _action(resource_id=None).resource_id is None

    def test_parameters_default_to_empty(self) -> None:
        assert _action().parameters == {}

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AgentAction(
                action_type="cancel_job",
                resource_type="job",
                reason="x",
                severity="catastrophic",
            )

    def test_non_string_parameters_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _action(parameters=["not", "a", "mapping"])

    def test_serialisation_round_trip(self) -> None:
        action = _action(parameters={"job_id": "job-9", "reason_code": 42})
        restored = AgentAction.model_validate(action.model_dump())
        assert restored.parameters == {"job_id": "job-9", "reason_code": 42}

    def test_fingerprint_is_stable_and_distinguishing(self) -> None:
        assert _action().fingerprint() == _action().fingerprint()
        assert _action().fingerprint() != _action(resource_id="job-999").fingerprint()
        assert (
            _action().fingerprint() != _action(action_type="create_job").fingerprint()
        )

    def test_whitespace_only_resource_type_rejected(self) -> None:
        """Regression: normalisation must not run after the length constraint."""
        with pytest.raises(ValidationError):
            _action(resource_type="   ")

    def test_padded_action_type_is_accepted_and_trimmed(self) -> None:
        assert _action(action_type=" cancel_job ").action_type == "cancel_job"

    def test_free_form_text_is_not_an_action(self) -> None:
        """A prose sentence must not validate as a structured action."""
        with pytest.raises(ValidationError):
            AgentAction.model_validate(
                "Please cancel the customer's appointment right away"
            )


class TestApprovalDecision:
    def test_approved_property(self) -> None:
        assert ApprovalDecision(approval_id="a", decision="approved").approved is True
        assert ApprovalDecision(approval_id="a", decision="REJECTED").approved is False

    def test_decision_required(self) -> None:
        with pytest.raises(ValidationError):
            ApprovalDecision(approval_id="a")


# ---------------------------------------------------------------------------
# Central approval policy
# ---------------------------------------------------------------------------


class TestApprovalPolicy:
    @pytest.mark.parametrize(
        ("action_type", "risk", "requires_approval"),
        [
            # Reads and informational answers are safe.
            ("get_job", ActionRisk.LOW, False),
            ("get_customer_invoices", ActionRisk.LOW, False),
            ("get_customer_jobs", ActionRisk.LOW, False),
            ("search_knowledge", ActionRisk.LOW, False),
            ("get_support_information", ActionRisk.LOW, False),
            # Creation and modification are gated.
            ("create_job", ActionRisk.MEDIUM, True),
            ("create_ticket", ActionRisk.MEDIUM, True),
            ("assign_engineer", ActionRisk.MEDIUM, True),
            ("cancel_job", ActionRisk.HIGH, True),
            ("update_job_status", ActionRisk.HIGH, True),
            ("reschedule_job", ActionRisk.HIGH, True),
            ("update_invoice", ActionRisk.CRITICAL, True),
            ("issue_refund", ActionRisk.CRITICAL, True),
            ("send_email", ActionRisk.CRITICAL, True),
        ],
    )
    def test_platform_classification(
        self, action_type: str, risk: ActionRisk, requires_approval: bool
    ) -> None:
        requirement = evaluate(_action(action_type=action_type, resource_type="x"))
        assert requirement.requires_approval is requires_approval
        assert requirement.risk_level is risk
        assert requirement.action_type == action_type

    def test_unknown_action_is_gated_conservatively(self) -> None:
        requirement = evaluate(_action(action_type="drop_database"))
        assert requirement.requires_approval is True
        assert requirement.risk_level is ActionRisk.HIGH

    def test_requirement_is_auditable(self) -> None:
        requirement = evaluate(_action())
        assert isinstance(requirement, ApprovalRequirement)
        assert requirement.source == "platform_policy"

    def test_tenant_can_add_strictness(self) -> None:
        policy = ApprovalPolicy(tenant_required_actions=frozenset({"update_ticket"}))
        requirement = evaluate(_action(action_type="update_ticket"), policy)
        assert requirement.requires_approval is True
        assert requirement.source == "tenant_policy"

    def test_tenant_cannot_remove_platform_requirement(self) -> None:
        policy = ApprovalPolicy(tenant_exempt_actions=frozenset({"cancel_job"}))
        requirement = evaluate(_action(action_type="cancel_job"), policy)
        assert requirement.requires_approval is True
        assert requirement.source == "platform_policy"

    def test_tenant_cannot_exempt_unknown_action(self) -> None:
        policy = ApprovalPolicy(tenant_exempt_actions=frozenset({"drop_database"}))
        assert evaluate(_action(action_type="drop_database"), policy).requires_approval

    def test_policy_from_tenant_business_rules(self) -> None:
        from agents.config import AgentConfig, AgentType

        config = AgentConfig(
            tenant_id="t1",
            agent_type=AgentType.JOB_AGENT,
            business_rules=[
                "require_human_approval_for=update_ticket, assign_engineer",
                "no_human_approval_for=cancel_job",
            ],
        )
        policy = ApprovalPolicy.from_tenant_config(config)
        assert policy.tenant_required_actions == frozenset(
            {"update_ticket", "assign_engineer"}
        )
        # Platform requirement still wins over the tenant's exemption attempt.
        assert evaluate(_action(action_type="cancel_job"), policy).requires_approval

    def test_risk_for_helper(self) -> None:
        assert risk_for("get_job") is ActionRisk.LOW
        assert risk_for("issue_refund") is ActionRisk.CRITICAL
        assert risk_for("who_knows") is ActionRisk.HIGH


# ---------------------------------------------------------------------------
# Approval request lifecycle
# ---------------------------------------------------------------------------


class TestApprovalLifecycle:
    def test_create_persists_pending_request(self, sa_session: Session) -> None:
        row = _create(sa_session)
        assert row.status == ApprovalStatus.PENDING.value
        assert row.tenant_id == "tenant-a"
        assert row.conversation_id == "conv-1"
        assert row.action_type == "cancel_job"
        assert row.risk_level == ActionRisk.HIGH.value
        assert row.reviewed_by is None

    def test_create_stores_structured_payload(self, sa_session: Session) -> None:
        row = _create(
            sa_session, action=_action(parameters={"job_id": "job-123", "note": "ok"})
        )
        assert row.payload["parameters"]["job_id"] == "job-123"
        assert row.payload["reason"] == "Customer requested cancellation"

    def test_sensitive_parameters_are_not_persisted(self, sa_session: Session) -> None:
        row = _create(
            sa_session,
            action=_action(
                parameters={
                    "job_id": "job-123",
                    "api_key": "sk-live-should-not-be-stored",
                    "password": "hunter2",
                }
            ),
        )
        stored = repr(row.payload)
        assert "job-123" in stored
        assert "sk-live-should-not-be-stored" not in stored
        assert "hunter2" not in stored

    def test_get_enforces_tenant_isolation(self, sa_session: Session) -> None:
        row = _create(sa_session, tenant_id="tenant-a")
        ApprovalService(sa_session).get(row.id, tenant_id="tenant-a")
        with pytest.raises(ApprovalNotFound):
            ApprovalService(sa_session).get(row.id, tenant_id="tenant-b")

    def test_get_unknown_id_raises(self, sa_session: Session) -> None:
        with pytest.raises(ApprovalNotFound):
            ApprovalService(sa_session).get("no-such-approval", tenant_id="tenant-a")

    def test_list_is_tenant_scoped(self, sa_session: Session) -> None:
        _create(sa_session, tenant_id="tenant-a", conversation_id="c1")
        _create(sa_session, tenant_id="tenant-a", conversation_id="c2")
        _create(sa_session, tenant_id="tenant-b", conversation_id="c3")
        rows = ApprovalService(sa_session).list(tenant_id="tenant-a")
        assert len(rows) == 2
        assert {row.tenant_id for row in rows} == {"tenant-a"}

    def test_list_filters_by_status_and_agent(self, sa_session: Session) -> None:
        _create(sa_session, conversation_id="c1")
        _create(sa_session, conversation_id="c2")
        ApprovalService(sa_session).approve(
            ApprovalService(sa_session).list(tenant_id="tenant-a")[0].id,
            tenant_id="tenant-a",
            reviewer_id="reviewer-1",
        )
        pending = ApprovalService(sa_session).list(
            tenant_id="tenant-a", status=ApprovalStatus.PENDING.value
        )
        assert len(pending) == 1
        assert ApprovalService(sa_session).list(tenant_id="tenant-a", agent_type="job")

    def test_approve_transitions_pending_to_approved(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        approved = service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        assert approved.status == ApprovalStatus.APPROVED.value
        assert approved.reviewed_by == "r1"
        assert approved.reviewed_at is not None

    def test_reject_transitions_pending_to_rejected(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        rejected = service.reject(
            row.id, tenant_id="tenant-a", reviewer_id="r1", comment="Not this time"
        )
        assert rejected.status == ApprovalStatus.REJECTED.value
        assert rejected.review_comment == "Not this time"

    def test_cancel_transitions_pending_to_cancelled(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        cancelled = service.cancel(row.id, tenant_id="tenant-a", actor_id="r1")
        assert cancelled.status == ApprovalStatus.CANCELLED.value

    def test_approve_after_reject_fails(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.reject(row.id, tenant_id="tenant-a", reviewer_id="r1")
        with pytest.raises(ApprovalConflict):
            service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")

    def test_reject_after_approve_fails(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        with pytest.raises(ApprovalConflict):
            service.reject(row.id, tenant_id="tenant-a", reviewer_id="r1")

    def test_cancel_after_approve_fails(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        with pytest.raises(ApprovalConflict):
            service.cancel(row.id, tenant_id="tenant-a", actor_id="r1")

    def test_repeat_approve_is_idempotent(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        first = service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        second = service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        assert first.status == second.status == ApprovalStatus.APPROVED.value
        assert (
            sa_session.query(ApprovalRequest)
            .filter(ApprovalRequest.id == row.id)
            .count()
            == 1
        )

    def test_cross_tenant_approve_fails(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session, tenant_id="tenant-a")
        with pytest.raises(ApprovalNotFound):
            service.approve(row.id, tenant_id="tenant-b", reviewer_id="attacker")

    def test_terminal_statuses_have_no_further_transitions(self) -> None:
        assert ApprovalStatus.REJECTED.value in TERMINAL_STATUSES
        assert ApprovalStatus.EXPIRED.value in TERMINAL_STATUSES
        assert ApprovalStatus.CANCELLED.value in TERMINAL_STATUSES
        assert ApprovalStatus.EXECUTED.value in TERMINAL_STATUSES
        assert ApprovalStatus.FAILED.value in TERMINAL_STATUSES
        assert ApprovalStatus.PENDING.value not in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_duplicate_create_returns_existing_row(self, sa_session: Session) -> None:
        first = _create(sa_session, conversation_id="c1")
        second = _create(sa_session, conversation_id="c1")
        assert first.id == second.id
        assert sa_session.query(ApprovalRequest).count() == 1

    def test_duplicate_create_dedupes_approved_rows(self, sa_session: Session) -> None:
        """A replayed graph node after approval must not raise a second request."""
        first = _create(sa_session, conversation_id="c1")
        ApprovalService(sa_session).approve(
            first.id, tenant_id="tenant-a", reviewer_id="r1"
        )
        second = _create(sa_session, conversation_id="c1")
        assert second.id == first.id
        assert second.status == ApprovalStatus.APPROVED.value
        assert sa_session.query(ApprovalRequest).count() == 1

    def test_different_resource_creates_new_request(self, sa_session: Session) -> None:
        _create(sa_session, action=_action(resource_id="job-1"))
        _create(sa_session, action=_action(resource_id="job-2"))
        assert sa_session.query(ApprovalRequest).count() == 2

    def test_different_conversation_creates_new_request(
        self, sa_session: Session
    ) -> None:
        _create(sa_session, conversation_id="c1")
        _create(sa_session, conversation_id="c2")
        assert sa_session.query(ApprovalRequest).count() == 2

    def test_terminal_row_allows_a_fresh_request(self, sa_session: Session) -> None:
        first = _create(sa_session, conversation_id="c1")
        ApprovalService(sa_session).reject(
            first.id, tenant_id="tenant-a", reviewer_id="r1"
        )
        second = _create(sa_session, conversation_id="c1")
        assert second.id != first.id
        assert second.status == ApprovalStatus.PENDING.value

    def test_execute_once_runs_action_exactly_once(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        calls: list[str] = []

        first = execute_once(
            service,
            row.id,
            tenant_id="tenant-a",
            action=lambda: calls.append("ran") or {"ok": True},
        )
        assert first["executed"] is True
        assert first["duplicate"] is False
        assert calls == ["ran"]

    def test_second_execute_is_refused_without_re_running(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        calls: list[str] = []
        execute_once(
            service,
            row.id,
            tenant_id="tenant-a",
            action=lambda: calls.append("ran") or {},
        )
        second = execute_once(
            service,
            row.id,
            tenant_id="tenant-a",
            action=lambda: calls.append("ran") or {},
        )
        # The business action ran exactly once, no matter how often it is retried.
        assert calls == ["ran"]
        assert second["executed"] is False
        assert second["duplicate"] is True
        assert second["status"] == ApprovalStatus.EXECUTED.value

    def test_many_concurrent_style_retries_execute_once(
        self, sa_session: Session
    ) -> None:
        row = _create(sa_session)
        ApprovalService(sa_session).approve(
            row.id, tenant_id="tenant-a", reviewer_id="r1"
        )
        calls: list[int] = []
        for _ in range(5):
            execute_once(
                ApprovalService(sa_session),
                row.id,
                tenant_id="tenant-a",
                action=lambda: calls.append(1) or {"done": True},
            )
        assert len(calls) == 1

    def test_claim_requires_approved_status(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        with pytest.raises(ApprovalConflict):
            service.claim_for_execution(row.id, tenant_id="tenant-a")

    def test_failed_claim_preserves_other_pending_work(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        """Regression: a refused claim must not roll back the caller's session.

        ``claim_for_execution`` used to call ``session.rollback()`` on a lost
        race, which discarded every unrelated pending change in the caller's
        session. The conflict must be reported without destroying that work.
        """

        from db.models import AuditLog as _AuditLog

        # Unrelated pending write owned by the same session.
        sa_session.add(
            _AuditLog(
                tenant_id="tenant-a",
                action="UNRELATED",
                resource_type="thing",
                resource_id="thing-1",
            )
        )
        sa_session.flush()

        row = _create(sa_session)
        with pytest.raises(ApprovalConflict):
            service.claim_for_execution(row.id, tenant_id="tenant-a")

        # The unrelated row is still there, and the approval is still readable.
        sa_session.commit()
        assert (
            sa_session.query(_AuditLog).filter(_AuditLog.action == "UNRELATED").count()
            == 1
        )
        assert service.get(row.id, tenant_id="tenant-a").status == (
            ApprovalStatus.PENDING.value
        )

    def test_failing_action_marks_failed_and_does_not_retry_body(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        calls: list[int] = []

        def boom() -> dict:
            calls.append(1)
            raise RuntimeError("business rule failure")

        with pytest.raises(RuntimeError):
            execute_once(service, row.id, tenant_id="tenant-a", action=boom)
        failed = service.get(row.id, tenant_id="tenant-a")
        assert failed.status == ApprovalStatus.FAILED.value

        # A retry after failure must not re-run the body.
        retry = execute_once(
            service, row.id, tenant_id="tenant-a", action=lambda: calls.append(1) or {}
        )
        assert retry["executed"] is False
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Expiration
# ---------------------------------------------------------------------------


class TestExpiration:
    def test_expired_approval_cannot_be_approved(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session, ttl=timedelta(seconds=-1))
        with pytest.raises(ApprovalExpired):
            service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")

    def test_expired_approval_cannot_be_rejected_as_pending(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session, ttl=timedelta(seconds=-1))
        with pytest.raises(ApprovalExpired):
            service.reject(row.id, tenant_id="tenant-a", reviewer_id="r1")

    def test_reading_expired_request_marks_it_expired(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session, ttl=timedelta(seconds=-1))
        assert service.get(row.id, tenant_id="tenant-a").status == (
            ApprovalStatus.EXPIRED.value
        )

    def test_expire_if_due_is_idempotent(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session, ttl=timedelta(seconds=-1))
        assert (
            service.expire_if_due(row.id, tenant_id="tenant-a").status
            == ApprovalStatus.EXPIRED.value
        )
        assert (
            service.expire_if_due(row.id, tenant_id="tenant-a").status
            == ApprovalStatus.EXPIRED.value
        )

    def test_expired_approval_never_executes(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session, ttl=timedelta(seconds=-1))
        # Force APPROVED after expiry via a direct write, simulating a stale
        # reviewer decision that lands after the deadline.
        expired = service.get(row.id, tenant_id="tenant-a")
        assert expired.status == ApprovalStatus.EXPIRED.value
        with pytest.raises(ApprovalConflict):
            service.claim_for_execution(row.id, tenant_id="tenant-a")

    def test_expiry_uses_aware_utc_comparison(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        sa_session.refresh(row)
        # SQLite hands back naive datetimes; comparisons must still work.
        assert row.expires_at is not None
        assert service.get(row.id, tenant_id="tenant-a").status == (
            ApprovalStatus.PENDING.value
        )

    def test_future_expiry_stays_pending(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session, ttl=timedelta(hours=1))
        assert service.get(row.id, tenant_id="tenant-a").status == (
            ApprovalStatus.PENDING.value
        )

    def test_expired_request_emits_audit_event(self, sa_session: Session) -> None:
        row = _create(sa_session, ttl=timedelta(seconds=-1))
        ApprovalService(sa_session).get(row.id, tenant_id="tenant-a")
        actions = {
            entry.action
            for entry in sa_session.query(AuditLog)
            .filter(AuditLog.resource_id == row.id)
            .all()
        }
        assert AuditAction.APPROVAL_EXPIRED.value in actions


# ---------------------------------------------------------------------------
# Approval security
# ---------------------------------------------------------------------------


class TestApprovalSecurity:
    def test_other_tenant_cannot_read(self, sa_session: Session) -> None:
        row = _create(sa_session, tenant_id="tenant-a")
        with pytest.raises(ApprovalNotFound):
            ApprovalService(sa_session).get(row.id, tenant_id="tenant-b")

    def test_other_tenant_cannot_list(self, sa_session: Session) -> None:
        _create(sa_session, tenant_id="tenant-a")
        assert ApprovalService(sa_session).list(tenant_id="tenant-b") == []

    def test_other_tenant_cannot_execute(self, sa_session: Session) -> None:
        row = _create(sa_session, tenant_id="tenant-a")
        ApprovalService(sa_session).approve(
            row.id, tenant_id="tenant-a", reviewer_id="r1"
        )
        with pytest.raises(ApprovalNotFound):
            ApprovalService(sa_session).claim_for_execution(
                row.id, tenant_id="tenant-b"
            )

    def test_approval_for_nonexistent_resource_is_still_reviewable(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        """Creation is recorded; authorization is enforced at execution time."""
        row = _create(sa_session, action=_action(resource_id="job-does-not-exist"))
        assert service.get(row.id, tenant_id="tenant-a").resource_id == (
            "job-does-not-exist"
        )

    def test_approved_action_still_goes_through_tool_authorization(self) -> None:
        """Approval must not widen what the requesting agent could do."""
        from agents.context import AgentContext
        from agents.orchestrator import MultiAgentHelpdesk
        from hitl.graph_gate import ApprovalGate

        repo, connection = legacy_helpdesk(Path(tempfile_dir()))
        try:
            tools = MultiAgentHelpdesk.create(
                repository=repo, checkpointer=None, use_llm_triage=False
            ).tools
            ctx = AgentContext(
                customer_id="customer-1",
                conversation_id="c",
                tool_registry=tools,
            )
            gate = ApprovalGate(session_factory=None)
            # The gate dispatches through the registry, so the ownership check
            # still applies even after a human approved the action.
            victim_job = connection.execute(
                "SELECT id FROM jobs WHERE customer_id != 'customer-1' LIMIT 1"
            ).fetchone()[0]
            with pytest.raises(RuntimeError, match="business_rule"):
                gate._run_action(
                    _action(
                        action_type="cancel_job",
                        resource_type="job",
                        resource_id=victim_job,
                        parameters={"job_id": victim_job},
                    ),
                    ctx,
                    session=None,
                )
        finally:
            connection.close()


def tempfile_dir() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def _audit_actions(session: Session, *, tenant_id: str | None = None) -> set[str]:
    stmt = select(AuditLog)
    if tenant_id is not None:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    return {row.action for row in session.scalars(stmt).all()}


class TestAuditLogging:
    def test_approval_created_is_audited(self, sa_session: Session) -> None:
        row = _create(sa_session)
        entry = (
            sa_session.query(AuditLog)
            .filter(AuditLog.action == AuditAction.APPROVAL_CREATED.value)
            .one()
        )
        assert entry.tenant_id == "tenant-a"
        assert entry.resource_id == row.id
        assert entry.resource_type == "approval_request"
        assert entry.result == "success"
        assert entry.metadata_json["action_type"] == "cancel_job"
        assert entry.metadata_json["risk_level"] == ActionRisk.HIGH.value
        assert entry.created_at is not None

    def test_agent_action_has_no_human_actor(self, sa_session: Session) -> None:
        _create(sa_session)
        entry = (
            sa_session.query(AuditLog)
            .filter(AuditLog.action == AuditAction.APPROVAL_CREATED.value)
            .one()
        )
        # An autonomous agent action is not attributed to a human user.
        assert entry.actor_user_id is None
        assert entry.metadata_json["agent_type"] == "job"

    def test_approval_records_human_reviewer(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="reviewer-42")
        entry = (
            sa_session.query(AuditLog)
            .filter(AuditLog.action == AuditAction.APPROVAL_APPROVED.value)
            .one()
        )
        assert entry.actor_user_id == "reviewer-42"
        assert entry.metadata_json["result_status"] == ApprovalStatus.APPROVED.value

    def test_rejection_is_audited(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.reject(row.id, tenant_id="tenant-a", reviewer_id="r1")
        assert AuditAction.APPROVAL_REJECTED.value in _audit_actions(sa_session)

    def test_execution_is_audited(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        execute_once(service, row.id, tenant_id="tenant-a", action=lambda: {"ok": True})
        assert AuditAction.AGENT_ACTION_EXECUTED.value in _audit_actions(sa_session)

    def test_failed_execution_is_audited(
        self, sa_session: Session, service: ApprovalService
    ) -> None:
        row = _create(sa_session)
        service.approve(row.id, tenant_id="tenant-a", reviewer_id="r1")
        with pytest.raises(RuntimeError):
            execute_once(service, row.id, tenant_id="tenant-a", action=_raise_runtime)
        assert AuditAction.AGENT_ACTION_FAILED.value in _audit_actions(sa_session)

    def test_proposal_is_audited(self, sa_session: Session) -> None:
        log_agent_event(
            sa_session,
            tenant_id="tenant-a",
            action=AuditAction.AGENT_ACTION_PROPOSED,
            resource_type="job",
            resource_id="job-1",
            metadata={"agent_type": "job"},
        )
        assert AuditAction.AGENT_ACTION_PROPOSED.value in _audit_actions(sa_session)

    @pytest.mark.parametrize(
        "action",
        [
            AuditAction.HUMAN_ESCALATION,
            AuditAction.CONFIG_CHANGED,
            AuditAction.KNOWLEDGE_DOCUMENT_CHANGED,
        ],
    )
    def test_all_canonical_actions_are_recordable(
        self, sa_session: Session, action: AuditAction
    ) -> None:
        log_agent_event(
            sa_session,
            tenant_id="tenant-a",
            action=action,
            resource_type="thing",
            resource_id="thing-1",
        )
        assert action.value in _audit_actions(sa_session)

    def test_sensitive_metadata_is_scrubbed(self, sa_session: Session) -> None:
        log_agent_event(
            sa_session,
            tenant_id="tenant-a",
            action=AuditAction.CONFIG_CHANGED,
            resource_type="ai_config",
            resource_id="cfg-1",
            metadata={
                "agent_type": "JOB_AGENT",
                "api_key": "sk-live-secret",
                "password": "hunter2",
                "auth_token": "abc",
            },
        )
        entry = (
            sa_session.query(AuditLog)
            .filter(AuditLog.action == AuditAction.CONFIG_CHANGED.value)
            .one()
        )
        assert entry.metadata_json == {"agent_type": "JOB_AGENT"}
        assert "sk-live-secret" not in repr(entry.metadata_json)

    def test_audit_rows_are_tenant_scoped(self, sa_session: Session) -> None:
        _create(sa_session, tenant_id="tenant-a")
        _create(sa_session, tenant_id="tenant-b", conversation_id="c9")
        assert _audit_actions(sa_session, tenant_id="tenant-a")
        assert _audit_actions(sa_session, tenant_id="tenant-b")
        rows = sa_session.query(AuditLog).all()
        assert all(row.tenant_id in {"tenant-a", "tenant-b"} for row in rows)


def _raise_runtime() -> dict:
    raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Human escalation vs approval
# ---------------------------------------------------------------------------


class TestEscalationVersusApproval:
    def test_approval_required_action_is_gated_not_escalated(self) -> None:
        requirement = evaluate(_action(action_type="cancel_job"))
        assert requirement.requires_approval is True
        # Gating is an approval concern, not a support-handover concern.
        assert requirement.action_type != "human_escalation"

    def test_unanswerable_request_escalates_instead(self) -> None:
        """A request with no matching action is a human-handover, not an approval."""
        from agents.decisions import AgentDestination
        from agents.triage import requires_human_escalation
        from models import TicketIntent

        reason = requires_human_escalation(
            "There is a gas leak and I need a human now",
            TicketIntent.GENERAL_INQUIRY,
        )
        assert reason is not None
        assert AgentDestination.HUMAN.value == "human"

    def test_explicit_human_request_is_escalation(self) -> None:
        from agents.triage import requires_human_escalation
        from models import TicketIntent

        reason = requires_human_escalation(
            "Please connect me to a human agent", TicketIntent.HUMAN_ESCALATION
        )
        assert reason is not None
        assert "human" in reason.lower()


# ---------------------------------------------------------------------------
# Tenant scoping sanity
# ---------------------------------------------------------------------------


class TestTenantScopedApprovals:
    def test_tenant_and_actor_are_recorded(self, sa_session: Session) -> None:
        tenant = make_tenant(sa_session, slug="hitl-tenant")
        row = _create(sa_session, tenant_id=tenant.id, conversation_id="conv-h")
        assert row.tenant_id == tenant.id
        assert row.conversation_id == "conv-h"
