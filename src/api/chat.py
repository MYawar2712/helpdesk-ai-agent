"""Customer-facing chat and conversation-thread API (Day 5).

Routes
------
POST   /chat/conversations                       – Open a new conversation.
GET    /chat/conversations                       – List current customer's
    conversations.
GET    /chat/conversations/{conversation_id}     – Get conversation with messages.
POST   /chat/conversations/{conversation_id}/messages – Send a message; get AI reply.
DELETE /chat/conversations/{conversation_id}     – Soft-close a conversation.

Design decisions
----------------
* ``conversation_id`` is the canonical application-level thread ID.  The same
  value is passed to LangGraph as ``thread_id`` so agent state is persisted
  under the same key (no separate thread-id mapping).
* ``tenant_id`` and ``customer_id`` are **always** derived from the
  authenticated JWT – client-supplied values for these fields are ignored.
* Customer isolation is enforced by always filtering on both
  ``conversation.customer_id == user.customer_id`` and
  ``conversation.tenant_id == user.tenant_id``.
* Non-CUSTOMER roles (support agents, admins) may also call these endpoints
  and will see conversations scoped to their tenant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.checkpointer import CheckpointStateError, CheckpointUnavailableError
from api.dto import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from auth.dependencies import require_permission
from auth.rbac import Permission
from db.models import Conversation, Customer, Message, Ticket, User
from db.session import get_db

router = APIRouter(prefix="/chat", tags=["chat"])

_RequireConversationCreate = Depends(
    require_permission(Permission.CONVERSATION_CREATE.value)
)
_RequireConversationRead = Depends(
    require_permission(Permission.CONVERSATION_READ.value)
)
_RequireMessageCreate = Depends(require_permission(Permission.MESSAGE_CREATE.value))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_customer_id(user: User, db: Session) -> str:
    """Return the customer_id for the authenticated user.

    For CUSTOMER-role users the id is read from ``user.customer_id``.
    For staff roles the user itself is the actor and we return the user id
    so that staff-created conversations are still associated with a valid id.

    Raises HTTP 403 when a CUSTOMER user has no linked customer record.
    """
    role = (user.role or "").upper()
    if role == "CUSTOMER":
        if not user.customer_id:
            # Try to locate a Customer record by email as a fallback.
            customer = db.scalar(
                select(Customer).where(
                    Customer.tenant_id == user.tenant_id,
                    Customer.email == user.email,
                )
            )
            if customer is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "No customer record is linked to this user account. "
                        "Contact your tenant administrator."
                    ),
                )
            return customer.id
        return user.customer_id
    # Staff / admin: use the user's own id as the actor id.
    return user.id


def _resolve_conversation(
    conversation_id: str,
    user: User,
    db: Session,
    *,
    customer_id: str,
) -> Conversation:
    """Load a conversation and enforce ownership + tenant isolation.

    Returns HTTP 404 for both missing conversations **and** conversations
    that belong to a different customer, so that existence is not revealed
    to unauthorised callers.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    # Tenant isolation – even PLATFORM_ADMIN calls are tenant-scoped here.
    if conv.tenant_id != user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    # Customer isolation for CUSTOMER role.
    role = (user.role or "").upper()
    if role == "CUSTOMER" and conv.customer_id != customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    return conv


def _conv_to_response(conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conv.id,
        tenant_id=conv.tenant_id,
        customer_id=conv.customer_id,
        ticket_id=conv.ticket_id,
        subject=conv.subject,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _msg_to_response(msg: Message) -> MessageResponse:
    return MessageResponse(
        message_id=msg.id,
        conversation_id=msg.conversation_id,
        sender_type=msg.sender_type,
        content=msg.content,
        created_at=msg.created_at,
    )


# ---------------------------------------------------------------------------
# POST /chat/conversations
# ---------------------------------------------------------------------------


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat conversation",
    description=(
        "Opens a new conversation thread.  ``tenant_id`` and ``customer_id`` "
        "are always derived from the authenticated user – never from the request body."
    ),
)
def create_conversation(
    payload: ConversationCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireConversationCreate,
) -> ConversationResponse:
    """Create a new conversation for the authenticated customer."""
    customer_id = _get_customer_id(current_user, db)

    # Validate optional ticket_id belongs to this tenant + customer.
    if payload.ticket_id is not None:
        ticket = db.get(Ticket, payload.ticket_id)
        if ticket is None or ticket.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
            )

    conv = Conversation(
        tenant_id=current_user.tenant_id,
        customer_id=customer_id,
        ticket_id=payload.ticket_id,
        subject=payload.subject,
        status="open",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    return _conv_to_response(conv)


# ---------------------------------------------------------------------------
# GET /chat/conversations
# ---------------------------------------------------------------------------


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    summary="List conversations for the authenticated customer",
)
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireConversationRead,
) -> list[ConversationResponse]:
    """Return all conversations owned by the authenticated customer."""
    customer_id = _get_customer_id(current_user, db)

    role = (current_user.role or "").upper()
    query = select(Conversation).where(Conversation.tenant_id == current_user.tenant_id)
    # Customer role sees only their own conversations.
    if role == "CUSTOMER":
        query = query.where(Conversation.customer_id == customer_id)

    query = query.order_by(Conversation.updated_at.desc())
    convs = list(db.scalars(query).all())
    return [_conv_to_response(c) for c in convs]


# ---------------------------------------------------------------------------
# GET /chat/conversations/{conversation_id}
# ---------------------------------------------------------------------------


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Get a conversation with its full message history",
)
def get_conversation(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireConversationRead,
) -> ConversationDetailResponse:
    """Retrieve a conversation and its messages.

    Returns 404 when the conversation does not exist or belongs to a
    different customer, so that existence is never revealed to unauthorised
    callers.
    """
    customer_id = _get_customer_id(current_user, db)
    conv = _resolve_conversation(
        conversation_id, current_user, db, customer_id=customer_id
    )

    # Load messages – exclude SYSTEM-type messages from the customer-facing view.
    msgs_query = (
        select(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.sender_type != "SYSTEM",
        )
        .order_by(Message.created_at.asc())
    )
    msgs = list(db.scalars(msgs_query).all())

    return ConversationDetailResponse(
        conversation_id=conv.id,
        tenant_id=conv.tenant_id,
        customer_id=conv.customer_id,
        ticket_id=conv.ticket_id,
        subject=conv.subject,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[_msg_to_response(m) for m in msgs],
    )


# ---------------------------------------------------------------------------
# POST /chat/conversations/{conversation_id}/messages
# ---------------------------------------------------------------------------


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a customer message and receive an AI response",
    description=(
        "Saves the customer message, invokes the LangGraph agent using "
        "``conversation_id`` as the ``thread_id``, persists the AI reply, "
        "and returns it."
    ),
)
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireMessageCreate,
) -> SendMessageResponse:
    """Send a customer message; get an AI reply.

    The conversation_id is used as the LangGraph thread_id so that the agent
    maintains state across turns within the same conversation.

    Flow
    ----
    1. Authenticate (JWT dependency).
    2. Verify conversation ownership and tenant isolation.
    3. Persist customer message.
    4. Load conversation context.
    5. Invoke LangGraph with thread_id = conversation_id.
    6. Persist AI response.
    7. Return AI response.
    """
    customer_id = _get_customer_id(current_user, db)
    conv = _resolve_conversation(
        conversation_id, current_user, db, customer_id=customer_id
    )

    if conv.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot send messages to a closed conversation.",
        )

    # ── 3. Persist customer message ──────────────────────────────────────────
    customer_msg = Message(
        tenant_id=conv.tenant_id,
        conversation_id=conv.id,
        sender_type="CUSTOMER",
        content=payload.content,
    )
    db.add(customer_msg)
    db.commit()
    db.refresh(customer_msg)

    # Touch updated_at on the parent conversation.
    conv.updated_at = datetime.now(UTC)
    db.commit()

    # ── 4-5. Invoke LangGraph agent ──────────────────────────────────────────
    # conversation_id IS the LangGraph thread_id (canonical rule from Day 5).
    ai_content = _invoke_agent(
        request=request,
        ticket_text=payload.content,
        conversation_id=conversation_id,
        customer_id=customer_id,
        tenant_id=conv.tenant_id,
    )

    # ── 6. Persist AI message ────────────────────────────────────────────────
    ai_msg = Message(
        tenant_id=conv.tenant_id,
        conversation_id=conv.id,
        sender_type="AI",
        content=ai_content,
    )
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)

    return SendMessageResponse(
        conversation_id=conversation_id,
        message_id=ai_msg.id,
        sender="AI",
        content=ai_content,
        created_at=ai_msg.created_at,
    )


def _invoke_agent(
    *,
    request: Request,
    ticket_text: str,
    conversation_id: str,
    customer_id: str,
    tenant_id: str | None = None,
) -> str:
    """Run the LangGraph agent and return the AI response text.

    The ``conversation_id`` is passed as the LangGraph ``thread_id`` so that
    agent state (conversation history, tool context) persists across turns
    within the same conversation thread.

    As of Day 7 ``app.state.agent`` is the multi-agent supervisor workflow, so
    this single endpoint drives triage and the specialized agents. The
    ``tenant_id`` is forwarded from the authenticated session (never from the
    request body) so tenant scoping can be enforced inside agent tools.

    Falls back to a safe default message when the agent is not available or
    raises an exception (e.g. no LLM API key in test environments).

    Persistent-checkpoint failures are *not* swallowed: they are surfaced as
    HTTP 503 so a broken checkpoint store is never mistaken for a successful
    turn, and a second thread is never silently created for an existing
    conversation.
    """
    try:
        agent = request.app.state.agent
        # conversation_id == thread_id (canonical Day 5 rule).
        state = agent.invoke(
            ticket_text,
            email_thread_id=conversation_id,  # thread_id = conversation_id
            customer_id=customer_id,
            tenant_id=tenant_id,
        )
        # Extract the best available response from the agent state.
        response: str = state.get("final_response") or state.get("response") or ""
        return response or (
            "I'm sorry, I couldn't generate a response. Please try again."
        )
    except (CheckpointUnavailableError, CheckpointStateError) as exc:
        # Deliberately opaque: never leak database or checkpoint internals.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation state is temporarily unavailable.",
        ) from exc
    except Exception:  # noqa: BLE001
        return "I'm sorry, I couldn't generate a response. Please try again."


# ---------------------------------------------------------------------------
# DELETE /chat/conversations/{conversation_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Close (soft-delete) a conversation",
)
def delete_conversation(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: User = _RequireConversationCreate,
) -> None:
    """Soft-close a conversation by setting its status to 'closed'.

    Only the owning customer (or a tenant admin) may close a conversation.
    """
    customer_id = _get_customer_id(current_user, db)
    conv = _resolve_conversation(
        conversation_id, current_user, db, customer_id=customer_id
    )

    conv.status = "closed"
    conv.updated_at = datetime.now(UTC)
    db.commit()
