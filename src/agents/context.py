"""Server-derived execution context for Day 7 agent tools.

Security model
--------------
Identity is **never** taken from model output. The API layer builds an
:class:`AgentContext` from the authenticated session, and every tool receives
that context as its first argument. The LLM only ever supplies domain arguments
(such as ``job_id``), never ``customer_id`` or ``tenant_id``.

That produces the required call chain::

    Agent -> Validated Tool -> Business Logic -> Authorization -> Database

Ownership and tenant checks are re-validated inside the business-logic layer on
every call, so even a manipulated tool argument cannot reach another
customer's records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.operations import CustomerIdentity


class AgentAuthorizationError(PermissionError):
    """Raised when an agent attempts an action outside its allowed scope."""


class AgentToolError(RuntimeError):
    """Raised when a tool cannot complete an otherwise valid request."""


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Trusted, server-derived context shared by every agent tool.

    Attributes:
        customer_id: Authenticated customer. Injected server-side, never by the LLM.
        tenant_id: Authenticated tenant, when the deployment is multi-tenant.
        conversation_id: Chat conversation, which doubles as the LangGraph thread id.
        tenant_scoped: Whether the underlying store enforces ``tenant_id``.
        config_service: Per-turn Day 8 configuration loader. A fresh instance is
            created for each request so tenant configuration is read once per
            agent execution and never cached across turns.
        tool_registry: Server-built Day 7 tool registry, so the Day 9 approval
            gate executes an approved action through the same authorized,
            scope-checked path an agent would normally use.
    """

    customer_id: str
    conversation_id: str
    tenant_id: str | None = None
    tenant_scoped: bool = False
    config_service: Any | None = None
    tool_registry: Any | None = None

    def __post_init__(self) -> None:
        if not self.customer_id or not self.customer_id.strip():
            raise ValueError("customer_id is required")
        if not self.conversation_id or not self.conversation_id.strip():
            raise ValueError("conversation_id is required")

    @property
    def identity(self) -> CustomerIdentity:
        """Return the identity object used by the business-logic layer."""

        return CustomerIdentity(customer_id=self.customer_id, tenant_id=self.tenant_id)

    def require_same_tenant(self, record: dict | None) -> dict | None:
        """Return ``record`` only when it belongs to this context's tenant.

        Stores that are not tenant-scoped (the local SQLite helpdesk database)
        skip the check; PostgreSQL-backed deployments enforce it here so a
        mis-scoped query cannot cross a tenant boundary.
        """

        if record is None or not self.tenant_scoped or self.tenant_id is None:
            return record
        record_tenant = record.get("tenant_id")
        if record_tenant is not None and record_tenant != self.tenant_id:
            raise AgentAuthorizationError(
                "record does not belong to the authenticated tenant"
            )
        return record
