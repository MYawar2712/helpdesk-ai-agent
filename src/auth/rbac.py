"""RBAC Roles, Permissions, Role-Permission Mapping, and Agent Authorization Matrix."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """System-wide RBAC roles."""

    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    TENANT_ADMIN = "TENANT_ADMIN"
    SUPPORT_AGENT = "SUPPORT_AGENT"
    AI_AGENT = "AI_AGENT"
    CUSTOMER = "CUSTOMER"


class Permission(StrEnum):
    """Centralized fine-grained permissions."""

    # Tenant management
    TENANT_READ = "tenant:read"
    TENANT_UPDATE = "tenant:update"

    # User management
    USER_READ = "user:read"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"

    # Customer management
    CUSTOMER_READ = "customer:read"
    CUSTOMER_CREATE = "customer:create"
    CUSTOMER_UPDATE = "customer:update"

    # Ticket management
    TICKET_READ = "ticket:read"
    TICKET_CREATE = "ticket:create"
    TICKET_UPDATE = "ticket:update"
    TICKET_CLOSE = "ticket:close"

    # Job management
    JOB_READ = "job:read"
    JOB_CREATE = "job:create"
    JOB_UPDATE = "job:update"
    JOB_CANCEL = "job:cancel"
    JOB_ASSIGN = "job:assign"

    # Invoice management
    INVOICE_READ = "invoice:read"
    INVOICE_CREATE = "invoice:create"
    INVOICE_UPDATE = "invoice:update"

    # Engineer management
    ENGINEER_READ = "engineer:read"
    ENGINEER_CREATE = "engineer:create"
    ENGINEER_UPDATE = "engineer:update"
    ENGINEER_ASSIGN = "engineer:assign"

    # AI Configuration
    AI_CONFIG_READ = "ai_config:read"
    AI_CONFIG_UPDATE = "ai_config:update"

    # Tenant knowledge base
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"

    # Agent execution
    AGENT_CONFIGURE = "agent:configure"
    AGENT_EXECUTE = "agent:execute"

    # Human-in-the-loop approvals
    APPROVAL_READ = "approval:read"
    APPROVAL_DECIDE = "approval:decide"

    # Audit Log
    AUDIT_LOG_READ = "audit_log:read"

    # Conversation management
    CONVERSATION_CREATE = "conversation:create"
    CONVERSATION_READ = "conversation:read"
    MESSAGE_CREATE = "message:create"


# Centralized Role -> Permission mapping
ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.PLATFORM_ADMIN.value: {p.value for p in Permission},
    Role.TENANT_ADMIN.value: {
        Permission.TENANT_READ.value,
        Permission.TENANT_UPDATE.value,
        Permission.USER_READ.value,
        Permission.USER_CREATE.value,
        Permission.USER_UPDATE.value,
        Permission.USER_DELETE.value,
        Permission.CUSTOMER_READ.value,
        Permission.CUSTOMER_CREATE.value,
        Permission.CUSTOMER_UPDATE.value,
        Permission.TICKET_READ.value,
        Permission.TICKET_CREATE.value,
        Permission.TICKET_UPDATE.value,
        Permission.TICKET_CLOSE.value,
        Permission.JOB_READ.value,
        Permission.JOB_CREATE.value,
        Permission.JOB_UPDATE.value,
        Permission.JOB_CANCEL.value,
        Permission.JOB_ASSIGN.value,
        Permission.INVOICE_READ.value,
        Permission.INVOICE_CREATE.value,
        Permission.INVOICE_UPDATE.value,
        Permission.ENGINEER_READ.value,
        Permission.ENGINEER_CREATE.value,
        Permission.ENGINEER_UPDATE.value,
        Permission.ENGINEER_ASSIGN.value,
        Permission.AI_CONFIG_READ.value,
        Permission.AI_CONFIG_UPDATE.value,
        Permission.KNOWLEDGE_READ.value,
        Permission.KNOWLEDGE_WRITE.value,
        Permission.AGENT_CONFIGURE.value,
        Permission.AGENT_EXECUTE.value,
        Permission.APPROVAL_READ.value,
        Permission.APPROVAL_DECIDE.value,
        Permission.AUDIT_LOG_READ.value,
    },
    Role.SUPPORT_AGENT.value: {
        Permission.CUSTOMER_READ.value,
        Permission.CUSTOMER_CREATE.value,
        Permission.CUSTOMER_UPDATE.value,
        Permission.TICKET_READ.value,
        Permission.TICKET_CREATE.value,
        Permission.TICKET_UPDATE.value,
        Permission.TICKET_CLOSE.value,
        Permission.JOB_READ.value,
        Permission.JOB_CREATE.value,
        Permission.JOB_UPDATE.value,
        Permission.JOB_CANCEL.value,
        Permission.JOB_ASSIGN.value,
        Permission.INVOICE_READ.value,
        Permission.ENGINEER_READ.value,
        Permission.AGENT_EXECUTE.value,
        Permission.APPROVAL_READ.value,
        Permission.APPROVAL_DECIDE.value,
    },
    Role.AI_AGENT.value: {
        Permission.TICKET_READ.value,
        Permission.TICKET_CREATE.value,
        Permission.TICKET_UPDATE.value,
        Permission.JOB_READ.value,
        Permission.JOB_CREATE.value,
        Permission.CUSTOMER_READ.value,
        Permission.INVOICE_READ.value,
        Permission.AGENT_EXECUTE.value,
    },
    Role.CUSTOMER.value: {
        Permission.CUSTOMER_READ.value,
        Permission.TICKET_READ.value,
        Permission.TICKET_CREATE.value,
        Permission.JOB_READ.value,
        Permission.JOB_CREATE.value,
        Permission.JOB_CANCEL.value,
        Permission.INVOICE_READ.value,
        Permission.CONVERSATION_CREATE.value,
        Permission.CONVERSATION_READ.value,
        Permission.MESSAGE_CREATE.value,
    },
}


def get_role_permissions(role: str) -> set[str]:
    """Return set of permission strings for a given role name."""
    normalized = role.upper()
    return ROLE_PERMISSIONS.get(normalized, set())


def has_permission(role: str, permission: str) -> bool:
    """Check if a given role has a specific permission."""
    return permission in get_role_permissions(role)


# AI Agent Authorization Foundations
# Matrix mapping specific subagent types to explicit allowed permissions
AGENT_PERMISSIONS: dict[str, set[str]] = {
    "JOB_AGENT": {
        Permission.JOB_READ.value,
        Permission.JOB_CREATE.value,
        Permission.JOB_ASSIGN.value,
    },
    "TICKET_AGENT": {
        Permission.TICKET_READ.value,
        Permission.TICKET_CREATE.value,
        Permission.TICKET_UPDATE.value,
    },
    "INQUIRY_AGENT": {
        Permission.CUSTOMER_READ.value,
        Permission.INVOICE_READ.value,
    },
}


def validate_agent_permission(agent_type: str, permission: str) -> bool:
    """Check if a specific subagent type is allowed to execute a permission."""
    allowed = AGENT_PERMISSIONS.get(agent_type, set())
    return permission in allowed
