"""Day 9 API tests for the approval review queue and audit log endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from day7_9_helpers import auth_header, make_customer, make_tenant, make_user
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agents.actions import AgentAction, ApprovalStatus
from agents.approval_policy import evaluate
from db.models import ApprovalRequest
from hitl.service import ApprovalService

APPROVALS = "/approvals"
AUDIT = "/audit-logs"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _action(resource_id: str = "job-1", action_type: str = "cancel_job") -> AgentAction:
    return AgentAction(
        action_type=action_type,
        resource_type="job",
        resource_id=resource_id,
        parameters={"job_id": resource_id},
        reason="Customer requested cancellation",
    )


def _seed(
    session: Session,
    tenant_id: str,
    *,
    conversation_id: str = "conv-1",
    resource_id: str = "job-1",
    ttl: timedelta = timedelta(hours=24),
) -> ApprovalRequest:
    """Create a PENDING approval directly in the same session the API uses."""

    action = _action(resource_id)
    return ApprovalService(session).create(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        agent_type="job",
        action=action,
        requirement=evaluate(action),
        requested_by="job",
        ttl=ttl,
    )


@pytest.fixture()
def admin(sa_session: Session, sa_settings):
    tenant = make_tenant(sa_session, slug="ap-admin")
    user = make_user(sa_session, tenant=tenant, role="TENANT_ADMIN")
    return tenant, user, auth_header(user, sa_settings)


@pytest.fixture()
def reviewer(sa_session: Session, sa_settings):
    tenant = make_tenant(sa_session, slug="ap-reviewer")
    user = make_user(sa_session, tenant=tenant, role="SUPPORT_AGENT")
    return tenant, user, auth_header(user, sa_settings)


@pytest.fixture()
def customer(sa_session: Session, sa_settings):
    tenant = make_tenant(sa_session, slug="ap-customer")
    person = make_customer(sa_session, tenant=tenant)
    user = make_user(sa_session, tenant=tenant, role="CUSTOMER", customer=person)
    return tenant, user, auth_header(user, sa_settings)


# ---------------------------------------------------------------------------
# /approvals
# ---------------------------------------------------------------------------


class TestApprovalListApi:
    def test_requires_authentication(self, sa_client: TestClient) -> None:
        assert sa_client.get(APPROVALS).status_code == status.HTTP_401_UNAUTHORIZED

    def test_support_agent_may_list(
        self, sa_client: TestClient, sa_session: Session, reviewer
    ) -> None:
        tenant, _, headers = reviewer
        _seed(sa_session, tenant.id)
        response = sa_client.get(APPROVALS, headers=headers)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    def test_customer_may_not_list(self, sa_client: TestClient, customer) -> None:
        _, _, headers = customer
        assert sa_client.get(APPROVALS, headers=headers).status_code == (
            status.HTTP_403_FORBIDDEN
        )

    def test_tenant_admin_may_list(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        _seed(sa_session, tenant.id)
        assert sa_client.get(APPROVALS, headers=headers).status_code == (
            status.HTTP_200_OK
        )

    def test_list_is_empty_for_new_tenant(self, sa_client: TestClient, admin) -> None:
        _, _, headers = admin
        assert sa_client.get(APPROVALS, headers=headers).json() == []

    def test_status_filter(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id, resource_id="job-a")
        _seed(sa_session, tenant.id, resource_id="job-b")
        ApprovalService(sa_session).approve(
            row.id, tenant_id=tenant.id, reviewer_id="r1"
        )
        pending = sa_client.get(f"{APPROVALS}?status=PENDING", headers=headers).json()
        assert len(pending) == 1
        assert pending[0]["status"] == ApprovalStatus.PENDING.value
        approved = sa_client.get(f"{APPROVALS}?status=APPROVED", headers=headers).json()
        assert len(approved) == 1


class TestApprovalDetailApi:
    def test_get_own_approval(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        response = sa_client.get(f"{APPROVALS}/{row.id}", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["id"] == row.id
        assert body["tenant_id"] == tenant.id
        assert body["action_type"] == "cancel_job"
        assert body["risk_level"] == "HIGH"

    def test_missing_approval_returns_404(self, sa_client: TestClient, admin) -> None:
        _, _, headers = admin
        assert (
            sa_client.get(f"{APPROVALS}/does-not-exist", headers=headers).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_customer_may_not_read(self, sa_client: TestClient, customer) -> None:
        _, _, headers = customer
        assert (
            sa_client.get(f"{APPROVALS}/anything", headers=headers).status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_status_endpoint_hides_internals(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        body = sa_client.get(f"{APPROVALS}/{row.id}/status", headers=headers).json()
        assert set(body) == {"id", "status", "action_type", "requires_human"}
        assert body["status"] == ApprovalStatus.PENDING.value
        assert body["requires_human"] is True
        # No payload, reviewer identity, or risk internals leak to the surface.
        assert "payload" not in body
        assert "reviewed_by" not in body
        assert "risk_level" not in body


class TestApprovalDecisionApi:
    def test_approve(self, sa_client: TestClient, sa_session: Session, admin) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        response = sa_client.post(
            f"{APPROVALS}/{row.id}/approve",
            json={"comment": "Looks fine"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == ApprovalStatus.APPROVED.value
        assert response.json()["review_comment"] == "Looks fine"

    def test_approve_without_body(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        response = sa_client.post(f"{APPROVALS}/{row.id}/approve", headers=headers)
        assert response.status_code == status.HTTP_200_OK

    def test_reject(self, sa_client: TestClient, sa_session: Session, admin) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        response = sa_client.post(
            f"{APPROVALS}/{row.id}/reject",
            json={"comment": "Cannot do that"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == ApprovalStatus.REJECTED.value
        assert response.json()["review_comment"] == "Cannot do that"

    def test_cancel(self, sa_client: TestClient, sa_session: Session, admin) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        response = sa_client.post(f"{APPROVALS}/{row.id}/cancel", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == ApprovalStatus.CANCELLED.value

    def test_approve_after_reject_returns_409(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        sa_client.post(f"{APPROVALS}/{row.id}/reject", headers=headers)
        response = sa_client.post(f"{APPROVALS}/{row.id}/approve", headers=headers)
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_double_approve_is_idempotent(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        first = sa_client.post(f"{APPROVALS}/{row.id}/approve", headers=headers)
        second = sa_client.post(f"{APPROVALS}/{row.id}/approve", headers=headers)
        assert first.status_code == second.status_code == status.HTTP_200_OK
        assert second.json()["status"] == ApprovalStatus.APPROVED.value
        # The repeated call created no second row.
        assert sa_session.query(ApprovalRequest).count() == 1

    def test_expired_approval_returns_409(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id, ttl=timedelta(seconds=-1))
        response = sa_client.post(f"{APPROVALS}/{row.id}/approve", headers=headers)
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "expired" in response.json()["detail"].lower()

    def test_decision_on_missing_approval_returns_404(
        self, sa_client: TestClient, admin
    ) -> None:
        _, _, headers = admin
        assert (
            sa_client.post(f"{APPROVALS}/nope/approve", headers=headers).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_oversized_comment_rejected(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        response = sa_client.post(
            f"{APPROVALS}/{row.id}/approve",
            json={"comment": "x" * 5000},
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_support_agent_may_decide(
        self, sa_client: TestClient, sa_session: Session, reviewer
    ) -> None:
        tenant, _, headers = reviewer
        row = _seed(sa_session, tenant.id)
        response = sa_client.post(f"{APPROVALS}/{row.id}/approve", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["reviewed_by"]

    def test_customer_may_not_decide(self, sa_client: TestClient, customer) -> None:
        _, _, headers = customer
        assert (
            sa_client.post(f"{APPROVALS}/any-id/approve", headers=headers).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert (
            sa_client.post(f"{APPROVALS}/any-id/reject", headers=headers).status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_unauthenticated_decision_fails(self, sa_client: TestClient) -> None:
        assert (
            sa_client.post(f"{APPROVALS}/any-id/approve").status_code
            == status.HTTP_401_UNAUTHORIZED
        )


class TestApprovalTenantIsolation:
    def test_other_tenant_cannot_read(
        self, sa_client: TestClient, sa_session: Session, admin, reviewer
    ) -> None:
        _, _, other_headers = reviewer
        row = _seed(sa_session, admin[0].id)
        assert (
            sa_client.get(f"{APPROVALS}/{row.id}", headers=other_headers).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_other_tenant_cannot_approve(
        self, sa_client: TestClient, sa_session: Session, admin, reviewer
    ) -> None:
        _, _, owner_headers = admin
        _, _, other_headers = reviewer
        row = _seed(sa_session, owner_headers and admin[0].id)
        assert (
            sa_client.post(
                f"{APPROVALS}/{row.id}/approve", headers=other_headers
            ).status_code
            == status.HTTP_404_NOT_FOUND
        )
        # The owner's row is untouched by the attacker's attempt.
        assert (
            sa_client.get(f"{APPROVALS}/{row.id}", headers=owner_headers).json()[
                "status"
            ]
            == ApprovalStatus.PENDING.value
        )

    def test_other_tenant_cannot_reject(
        self, sa_client: TestClient, sa_session: Session, admin, reviewer
    ) -> None:
        _, _, other_headers = reviewer
        row = _seed(sa_session, admin[0].id)
        assert (
            sa_client.post(
                f"{APPROVALS}/{row.id}/reject", headers=other_headers
            ).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_other_tenant_list_is_empty(
        self, sa_client: TestClient, sa_session: Session, admin, reviewer
    ) -> None:
        _seed(sa_session, admin[0].id)
        assert sa_client.get(APPROVALS, headers=reviewer[2]).json() == []


# ---------------------------------------------------------------------------
# /audit-logs
# ---------------------------------------------------------------------------


class TestAuditLogApi:
    def test_requires_authentication(self, sa_client: TestClient) -> None:
        assert sa_client.get(AUDIT).status_code == status.HTTP_401_UNAUTHORIZED

    def test_tenant_admin_may_read(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        response = sa_client.get(AUDIT, headers=headers)
        assert response.status_code == status.HTTP_200_OK
        actions = {item["action"] for item in response.json()}
        assert "APPROVAL_CREATED" in actions
        assert all(item["tenant_id"] == tenant.id for item in response.json())
        assert any(item["resource_id"] == row.id for item in response.json())

    def test_audit_entries_carry_full_provenance(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        ApprovalService(sa_session).approve(
            row.id, tenant_id=tenant.id, reviewer_id="reviewer-9"
        )
        items = sa_client.get(
            f"{AUDIT}?action=APPROVAL_APPROVED", headers=headers
        ).json()
        assert len(items) == 1
        entry = items[0]
        assert entry["tenant_id"] == tenant.id
        assert entry["actor_user_id"] == "reviewer-9"
        assert entry["action"] == "APPROVAL_APPROVED"
        assert entry["resource_type"] == "approval_request"
        assert entry["resource_id"] == row.id
        assert entry["result"] == "success"
        assert entry["metadata"]["action_type"] == "cancel_job"
        assert entry["created_at"]

    def test_timestamps_are_recorded_and_recent(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        _seed(sa_session, tenant.id)
        items = sa_client.get(AUDIT, headers=headers).json()
        assert items
        assert all(item["created_at"] for item in items)
        # SQLite hands back naive datetimes for a ``timezone=True`` column, so
        # the value is compared as UTC. PostgreSQL returns an aware value.
        created = datetime.fromisoformat(items[0]["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        assert created <= datetime.now(UTC)

    def test_support_agent_may_not_read(self, sa_client: TestClient, reviewer) -> None:
        _, _, headers = reviewer
        assert sa_client.get(AUDIT, headers=headers).status_code == (
            status.HTTP_403_FORBIDDEN
        )

    def test_customer_may_not_read(self, sa_client: TestClient, customer) -> None:
        _, _, headers = customer
        assert sa_client.get(AUDIT, headers=headers).status_code == (
            status.HTTP_403_FORBIDDEN
        )

    def test_each_admin_sees_only_their_own_tenant(
        self, sa_client: TestClient, sa_session: Session, sa_settings, admin
    ) -> None:
        tenant, _, _ = admin
        _seed(sa_session, tenant.id)
        other_tenant = make_tenant(sa_session, slug="ap-audit-other")
        other_admin = make_user(sa_session, tenant=other_tenant, role="TENANT_ADMIN")
        headers = auth_header(other_admin, sa_settings)
        assert sa_client.get(AUDIT, headers=headers).json() == []

    def test_filter_by_action(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        _seed(sa_session, tenant.id)
        filtered = sa_client.get(
            f"{AUDIT}?action=APPROVAL_CREATED", headers=headers
        ).json()
        assert filtered
        assert all(item["action"] == "APPROVAL_CREATED" for item in filtered)
        assert (
            sa_client.get(f"{AUDIT}?action=NO_SUCH_EVENT", headers=headers).json() == []
        )

    def test_filter_by_resource_id(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        tenant, _, headers = admin
        row = _seed(sa_session, tenant.id)
        filtered = sa_client.get(
            f"{AUDIT}?resource_id={row.id}", headers=headers
        ).json()
        assert filtered
        assert all(item["resource_id"] == row.id for item in filtered)

    def test_invalid_limit_rejected(self, sa_client: TestClient, admin) -> None:
        _, _, headers = admin
        assert (
            sa_client.get(f"{AUDIT}?limit=0", headers=headers).status_code
            == status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        assert (
            sa_client.get(f"{AUDIT}?limit=9999", headers=headers).status_code
            == status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    def test_no_mutation_endpoints(self, sa_client: TestClient, admin) -> None:
        """Audit records are append-only, so the router exposes no writes."""

        _, _, headers = admin
        assert sa_client.post(AUDIT, json={}, headers=headers).status_code in {
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        }
        assert sa_client.delete(AUDIT, headers=headers).status_code in {
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        }

    def test_sensitive_values_are_not_exposed(
        self, sa_client: TestClient, sa_session: Session, admin
    ) -> None:
        from hitl.audit_events import AuditAction, log_agent_event

        tenant, _, headers = admin
        log_agent_event(
            sa_session,
            tenant_id=tenant.id,
            action=AuditAction.CONFIG_CHANGED,
            resource_type="ai_config",
            resource_id="cfg-1",
            metadata={
                "agent_type": "JOB_AGENT",
                "api_key": "sk-live-should-not-appear",
                "password": "hunter2",
            },
        )
        items = sa_client.get(f"{AUDIT}?action=CONFIG_CHANGED", headers=headers).json()
        assert items
        serialized = str(items)
        assert "sk-live-should-not-appear" not in serialized
        assert "hunter2" not in serialized
        assert items[0]["metadata"] == {"agent_type": "JOB_AGENT"}
