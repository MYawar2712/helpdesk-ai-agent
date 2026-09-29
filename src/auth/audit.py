"""Audit logging utility for RBAC & security events."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.models import AuditLog


def log_security_event(
    session: Session,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_user_id: str | None = None,
    tenant_id: str | None = None,
    result: str = "success",
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Record an audit log entry for security and authorization events.

    NEVER log passwords, JWTs, API keys, or raw credentials in metadata.
    """
    safe_metadata = {}
    if metadata:
        for k, v in metadata.items():
            if any(
                sensitive in k.lower()
                for sensitive in ("password", "token", "jwt", "secret", "key", "auth")
            ):
                continue
            safe_metadata[k] = str(v)

    audit_entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        metadata_json=safe_metadata if safe_metadata else None,
    )
    session.add(audit_entry)
    session.commit()
    return audit_entry
