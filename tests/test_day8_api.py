"""Day 8 API tests for /ai-config and /knowledge endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from day7_9_helpers import (
    auth_header,
    make_customer,
    make_tenant,
    make_user,
)
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

CONFIG_URL = "/ai-config"
KNOWLEDGE_URL = "/knowledge/documents"


@pytest.fixture()
def tenant_admin(sa_session: Session, sa_settings):
    tenant = make_tenant(sa_session, slug="api-admin")
    user = make_user(sa_session, tenant=tenant, role="TENANT_ADMIN")
    return tenant, user, auth_header(user, sa_settings)


@pytest.fixture()
def other_tenant_admin(sa_session: Session, sa_settings):
    tenant = make_tenant(sa_session, slug="api-other")
    user = make_user(sa_session, tenant=tenant, role="TENANT_ADMIN")
    return tenant, user, auth_header(user, sa_settings)


# ---------------------------------------------------------------------------
# /ai-config
# ---------------------------------------------------------------------------


class TestAIConfigApi:
    def test_requires_authentication(self, sa_client: TestClient) -> None:
        assert sa_client.get(CONFIG_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_and_get(self, sa_client: TestClient, tenant_admin) -> None:
        _, _, headers = tenant_admin
        created = sa_client.post(
            CONFIG_URL,
            json={"agent_type": "SUPPORT_AGENT", "instructions": "Be friendly."},
            headers=headers,
        )
        assert created.status_code == status.HTTP_201_CREATED
        body = created.json()
        assert body["agent_type"] == "SUPPORT_AGENT"
        assert body["instructions"] == "Be friendly."

        fetched = sa_client.get(f"{CONFIG_URL}/SUPPORT_AGENT", headers=headers)
        assert fetched.status_code == status.HTTP_200_OK
        assert fetched.json()["instructions"] == "Be friendly."

    def test_list_configs(self, sa_client: TestClient, tenant_admin) -> None:
        _, _, headers = tenant_admin
        sa_client.post(
            CONFIG_URL,
            json={"agent_type": "JOB_AGENT", "instructions": "Strict."},
            headers=headers,
        )
        listed = sa_client.get(CONFIG_URL, headers=headers)
        assert listed.status_code == status.HTTP_200_OK
        assert any(item["agent_type"] == "JOB_AGENT" for item in listed.json())

    def test_patch_updates(self, sa_client: TestClient, tenant_admin) -> None:
        _, _, headers = tenant_admin
        sa_client.post(
            CONFIG_URL,
            json={"agent_type": "INVOICE_AGENT", "instructions": "A"},
            headers=headers,
        )
        # The upsert model is shared by POST and PATCH, so agent_type is
        # supplied in the body as well as the path.
        patched = sa_client.patch(
            f"{CONFIG_URL}/INVOICE_AGENT",
            json={
                "agent_type": "INVOICE_AGENT",
                "instructions": "B",
                "tone": "formal",
            },
            headers=headers,
        )
        assert patched.status_code == status.HTTP_200_OK
        assert patched.json()["instructions"] == "B"
        assert patched.json()["tone"] == "formal"

    def test_invalid_agent_type_rejected(
        self, sa_client: TestClient, tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        response = sa_client.post(
            CONFIG_URL,
            json={"agent_type": "NOT_AN_AGENT", "instructions": "x"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_duplicate_create_conflicts(
        self, sa_client: TestClient, tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        payload = {"agent_type": "SUPPORT_AGENT", "instructions": "x"}
        sa_client.post(CONFIG_URL, json=payload, headers=headers)
        second = sa_client.post(CONFIG_URL, json=payload, headers=headers)
        assert second.status_code == status.HTTP_409_CONFLICT

    def test_missing_config_returns_404(
        self, sa_client: TestClient, tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        assert (
            sa_client.get(f"{CONFIG_URL}/JOB_AGENT", headers=headers).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_cannot_read_other_tenant_config(
        self, sa_client: TestClient, tenant_admin, other_tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        _, _, other_headers = other_tenant_admin
        sa_client.post(
            CONFIG_URL,
            json={"agent_type": "SUPPORT_AGENT", "instructions": "Tenant A secret"},
            headers=headers,
        )
        # Tenant B cannot see Tenant A's config.
        assert (
            sa_client.get(
                f"{CONFIG_URL}/SUPPORT_AGENT", headers=other_headers
            ).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_body_tenant_id_is_ignored_for_authorization(
        self, sa_client: TestClient, tenant_admin
    ) -> None:
        """A tenant_id in the body must not determine who owns the config."""
        tenant, _, headers = tenant_admin
        created = sa_client.post(
            CONFIG_URL,
            json={
                "agent_type": "JOB_AGENT",
                "instructions": "x",
                "tenant_id": "attacker-tenant",
            },
            headers=headers,
        )
        # The config is created under the authenticated tenant, not the body value.
        assert created.status_code == status.HTTP_201_CREATED
        assert created.json()["tenant_id"] == tenant.id

    def test_customer_role_cannot_update(
        self, sa_client: TestClient, sa_session: Session, sa_settings
    ) -> None:
        tenant = make_tenant(sa_session, slug="cfg-customer")
        customer = make_customer(sa_session, tenant=tenant)
        user = make_user(sa_session, tenant=tenant, role="CUSTOMER", customer=customer)
        headers = auth_header(user, sa_settings)
        response = sa_client.post(
            CONFIG_URL,
            json={"agent_type": "SUPPORT_AGENT", "instructions": "x"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# /knowledge/documents
# ---------------------------------------------------------------------------


class TestKnowledgeApi:
    def test_requires_authentication(self, sa_client: TestClient) -> None:
        assert sa_client.get(KNOWLEDGE_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_upload_document(self, sa_client: TestClient, tenant_admin) -> None:
        _, _, headers = tenant_admin
        response = sa_client.post(
            KNOWLEDGE_URL,
            files={"file": ("policy.md", b"Refunds take five days.", "text/markdown")},
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["processing_status"] == "ready"
        assert body["chunk_count"] >= 1

    def test_upload_rejects_unsupported_type(
        self, sa_client: TestClient, tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        response = sa_client.post(
            KNOWLEDGE_URL,
            files={"file": ("bad.exe", b"binary", "application/octet-stream")},
            headers=headers,
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_and_get_document(
        self, sa_client: TestClient, tenant_admin, tmp_path: Path
    ) -> None:
        tenant, _, headers = tenant_admin
        sa_client.post(
            KNOWLEDGE_URL,
            files={"file": ("policy.md", b"Refunds take five days.", "text/markdown")},
            headers=headers,
        )
        listed = sa_client.get(KNOWLEDGE_URL, headers=headers)
        assert listed.status_code == status.HTTP_200_OK
        assert len(listed.json()) == 1
        doc_id = listed.json()[0]["id"]

        fetched = sa_client.get(f"{KNOWLEDGE_URL}/{doc_id}", headers=headers)
        assert fetched.status_code == status.HTTP_200_OK
        assert fetched.json()["id"] == doc_id

    def test_get_missing_document_404(
        self, sa_client: TestClient, tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        assert (
            sa_client.get(
                f"{KNOWLEDGE_URL}/does-not-exist", headers=headers
            ).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_cannot_read_other_tenant_document(
        self, sa_client: TestClient, tenant_admin, other_tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        _, _, other_headers = other_tenant_admin
        created = sa_client.post(
            KNOWLEDGE_URL,
            files={"file": ("policy.md", b"secret", "text/markdown")},
            headers=headers,
        )
        doc_id = created.json()["id"]
        # Tenant B cannot read Tenant A's document.
        assert (
            sa_client.get(
                f"{KNOWLEDGE_URL}/{doc_id}", headers=other_headers
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_cannot_delete_other_tenant_document(
        self, sa_client: TestClient, tenant_admin, other_tenant_admin
    ) -> None:
        _, _, headers = tenant_admin
        _, _, other_headers = other_tenant_admin
        created = sa_client.post(
            KNOWLEDGE_URL,
            files={"file": ("policy.md", b"secret", "text/markdown")},
            headers=headers,
        )
        doc_id = created.json()["id"]
        assert (
            sa_client.delete(
                f"{KNOWLEDGE_URL}/{doc_id}", headers=other_headers
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_delete_own_document(self, sa_client: TestClient, tenant_admin) -> None:
        _, _, headers = tenant_admin
        created = sa_client.post(
            KNOWLEDGE_URL,
            files={"file": ("policy.md", b"bye", "text/markdown")},
            headers=headers,
        )
        doc_id = created.json()["id"]
        assert (
            sa_client.delete(f"{KNOWLEDGE_URL}/{doc_id}", headers=headers).status_code
            == status.HTTP_204_NO_CONTENT
        )

    def test_customer_role_cannot_upload(
        self, sa_client: TestClient, sa_session: Session, sa_settings
    ) -> None:
        tenant = make_tenant(sa_session, slug="kb-customer")
        customer = make_customer(sa_session, tenant=tenant)
        user = make_user(sa_session, tenant=tenant, role="CUSTOMER", customer=customer)
        headers = auth_header(user, sa_settings)
        response = sa_client.post(
            KNOWLEDGE_URL,
            files={"file": ("policy.md", b"x", "text/markdown")},
            headers=headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
