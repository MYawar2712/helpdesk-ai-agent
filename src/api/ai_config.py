"""Tenant AI configuration endpoints (Day 8).

Tenant identity is always derived from the authenticated user. ``tenant_id`` is
never accepted from a request body as the source of authorization; a body value
of a *different* tenant is either ignored or rejected.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.config import AgentType
from auth.dependencies import require_permission, verify_tenant_access
from auth.rbac import Permission, Role
from db.models import AIConfiguration, User
from db.session import get_db

router = APIRouter(prefix="/ai-config", tags=["ai-config"])


class AIConfigResponse(BaseModel):
    """Serialized agent configuration."""

    id: str
    tenant_id: str
    agent_type: str
    instructions: str | None = None
    global_instructions: str | None = None
    tone: str | None = None
    business_rules: list[str] = Field(default_factory=list)
    escalation_rules: list[str] = Field(default_factory=list)
    allowed_tools: list[str] | None = None
    is_active: bool = True

    @classmethod
    def from_model(cls, row: AIConfiguration) -> AIConfigResponse:
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            agent_type=row.agent_type,
            instructions=row.instructions,
            global_instructions=row.global_instructions,
            tone=row.tone,
            business_rules=_as_list(row.business_rules),
            escalation_rules=_as_list(row.escalation_rules),
            allowed_tools=(
                _as_list(row.allowed_tools) if row.allowed_tools is not None else None
            ),
            is_active=bool(row.is_active),
        )


class AIConfigUpsertRequest(BaseModel):
    """Payload for creating or updating one agent's configuration."""

    agent_type: str
    instructions: str | None = None
    global_instructions: str | None = None
    tone: str | None = None
    business_rules: list[str] | None = None
    escalation_rules: list[str] | None = None
    allowed_tools: list[str] | None = None
    is_active: bool | None = None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [str(item).strip() for item in value.values() if str(item).strip()]
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _require_known_agent_type(value: str) -> str:
    """Reject unknown agent types instead of silently storing junk."""

    try:
        return AgentType(value.strip().upper()).value
    except (AttributeError, ValueError) as error:
        allowed = ", ".join(item.value for item in AgentType)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown agent_type. Expected one of: {allowed}",
        ) from error


def _tenant_id(current_user: User) -> str | None:
    if (current_user.role or "").upper() == Role.PLATFORM_ADMIN.value:
        return current_user.tenant_id
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a tenant.",
        )
    return current_user.tenant_id


@router.get("", response_model=list[AIConfigResponse], summary="List agent configs")
def list_ai_configs(
    current_user: Annotated[
        User, Depends(require_permission(Permission.AI_CONFIG_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> list[AIConfigResponse]:
    """Return every agent configuration for the authenticated tenant."""

    tenant_id = _tenant_id(current_user)
    stmt = select(AIConfiguration)
    if tenant_id is not None:
        stmt = stmt.where(AIConfiguration.tenant_id == tenant_id)
    rows = db.scalars(stmt.order_by(AIConfiguration.agent_type)).all()
    return [AIConfigResponse.from_model(row) for row in rows]


@router.get(
    "/{agent_type}", response_model=AIConfigResponse, summary="Get one agent config"
)
def get_ai_config(
    agent_type: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.AI_CONFIG_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> AIConfigResponse:
    """Return the configuration for one agent type of this tenant."""

    resolved = _require_known_agent_type(agent_type)
    tenant_id = _tenant_id(current_user)
    row = db.scalars(
        select(AIConfiguration).where(
            AIConfiguration.tenant_id == tenant_id,
            AIConfiguration.agent_type == resolved,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {resolved} configuration for this tenant.",
        )
    return AIConfigResponse.from_model(row)


@router.post(
    "",
    response_model=AIConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent config",
)
def create_ai_config(
    payload: AIConfigUpsertRequest,
    current_user: Annotated[
        User, Depends(require_permission(Permission.AI_CONFIG_UPDATE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> AIConfigResponse:
    """Create configuration for one agent type of the authenticated tenant."""

    resolved = _require_known_agent_type(payload.agent_type)
    tenant_id = _tenant_id(current_user)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A tenant is required to create configuration.",
        )

    existing = db.scalars(
        select(AIConfiguration).where(
            AIConfiguration.tenant_id == tenant_id,
            AIConfiguration.agent_type == resolved,
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{resolved} configuration already exists; use PATCH to update.",
        )

    row = AIConfiguration(tenant_id=tenant_id, agent_type=resolved)
    _apply_payload(row, payload)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configuration already exists for this agent type.",
        ) from error
    db.refresh(row)
    return AIConfigResponse.from_model(row)


@router.patch(
    "/{agent_type}", response_model=AIConfigResponse, summary="Update an agent config"
)
def update_ai_config(
    agent_type: str,
    payload: AIConfigUpsertRequest,
    current_user: Annotated[
        User, Depends(require_permission(Permission.AI_CONFIG_UPDATE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> AIConfigResponse:
    """Update this tenant's configuration for one agent type."""

    resolved = _require_known_agent_type(agent_type)
    tenant_id = _tenant_id(current_user)
    row = db.scalars(
        select(AIConfiguration).where(
            AIConfiguration.tenant_id == tenant_id,
            AIConfiguration.agent_type == resolved,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {resolved} configuration for this tenant.",
        )
    # Belt-and-braces: never let a payload retarget another tenant's row.
    verify_tenant_access(current_user, row.tenant_id)

    _apply_payload(row, payload, agent_type=resolved)
    db.commit()
    db.refresh(row)
    return AIConfigResponse.from_model(row)


def _apply_payload(
    row: AIConfiguration,
    payload: AIConfigUpsertRequest,
    *,
    agent_type: str | None = None,
) -> None:
    """Copy the payload onto the row, ignoring unset fields."""

    if agent_type is not None:
        row.agent_type = agent_type
    if payload.instructions is not None:
        row.instructions = payload.instructions
    if payload.global_instructions is not None:
        row.global_instructions = payload.global_instructions
    if payload.tone is not None:
        row.tone = payload.tone
    if payload.business_rules is not None:
        row.business_rules = list(payload.business_rules)
    if payload.escalation_rules is not None:
        row.escalation_rules = list(payload.escalation_rules)
    if payload.allowed_tools is not None:
        row.allowed_tools = list(payload.allowed_tools)
    if payload.is_active is not None:
        row.is_active = payload.is_active
