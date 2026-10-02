"""Tenant knowledge-base document endpoints (Day 8).

Every read and write is scoped to ``current_user.tenant_id`` derived from the
authenticated session. A tenant can never list, read, or delete another
tenant's documents, and processing errors are reported as short safe messages
rather than stack traces.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.dependencies import require_permission, verify_tenant_access
from auth.rbac import Permission, Role
from db.models import KnowledgeDocument, User
from db.session import get_db
from rag.documents import (
    ALLOWED_SUFFIXES,
    DocumentProcessingError,
    DocumentStatus,
    delete_document,
    process_document,
)
from rag.tenant_store import TenantVectorStore

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

#: Directory where uploaded tenant documents are stored.
UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "data" / "knowledge_uploads"

#: Lazily-built, process-wide tenant vector store (Chroma). Building is deferred
#: so the API still starts when no embedding API key is configured; in that case
#: documents are chunked and stored relationally but not embedded.
_VECTOR_STORE: TenantVectorStore | None = None
_VECTOR_STORE_READY = False


def _vector_store() -> TenantVectorStore | None:
    """Return the shared tenant vector store, or ``None`` when unavailable."""

    global _VECTOR_STORE, _VECTOR_STORE_READY
    if _VECTOR_STORE_READY:
        return _VECTOR_STORE
    try:
        from rag.ingest import create_embedding_model

        _VECTOR_STORE = TenantVectorStore(embeddings=create_embedding_model())
    except Exception:  # noqa: BLE001 - embeddings are optional
        _VECTOR_STORE = None
    _VECTOR_STORE_READY = True
    return _VECTOR_STORE


class KnowledgeDocumentResponse(BaseModel):
    """Serialized knowledge document metadata."""

    id: str
    tenant_id: str
    name: str
    processing_status: str
    chunk_count: int = 0
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_model(cls, row: KnowledgeDocument) -> KnowledgeDocumentResponse:
        metadata = dict(row.doc_metadata or {})
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            processing_status=row.processing_status,
            chunk_count=int(metadata.get("chunk_count", 0) or 0),
            error=metadata.get("error"),
            created_at=(row.created_at.isoformat() if row.created_at else None),
            updated_at=(row.updated_at.isoformat() if row.updated_at else None),
        )


def _tenant_id(current_user: User) -> str:
    """Return the authenticated tenant, rejecting users without one."""

    if (current_user.role or "").upper() == Role.PLATFORM_ADMIN.value:
        tenant_id = current_user.tenant_id
    else:
        tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with a tenant.",
        )
    return tenant_id


def _load_document(
    db: Session, current_user: User, document_id: str
) -> KnowledgeDocument:
    """Load a document and enforce tenant ownership."""

    row = db.scalars(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )
    verify_tenant_access(current_user, row.tenant_id)
    return row


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a knowledge document",
)
async def upload_document(
    current_user: Annotated[
        User, Depends(require_permission(Permission.KNOWLEDGE_WRITE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
    name: Annotated[str | None, Form()] = None,
) -> KnowledgeDocumentResponse:
    """Store a document for the authenticated tenant and process it.

    The tenant comes from the authenticated user only; a client cannot upload
    into another tenant's knowledge base.
    """

    tenant_id = _tenant_id(current_user)
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A file name is required.",
        )
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported file type. Upload a .md, .txt, .html, or .htm file.",
        )

    document_id = str(uuid.uuid4())
    # Store under a per-tenant directory so one tenant's files are never mixed.
    directory = UPLOAD_ROOT / tenant_id
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{document_id}{Path(filename).suffix.lower()}"
    try:
        destination.write_bytes(await file.read())
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The file could not be stored.",
        ) from error

    row = KnowledgeDocument(
        id=document_id,
        tenant_id=tenant_id,
        name=(name or filename)[:255],
        file_path=str(destination),
        processing_status=DocumentStatus.PENDING.value,
        doc_metadata={"original_name": filename},
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Processing is synchronous but isolated: a failure marks the document
    # FAILED and never leaks an internal traceback to the caller.
    try:
        process_document(session=db, document=row, vector_store=_vector_store())
    except DocumentProcessingError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    db.refresh(row)
    return KnowledgeDocumentResponse.from_model(row)


@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentResponse],
    summary="List tenant knowledge documents",
)
def list_documents(
    current_user: Annotated[
        User, Depends(require_permission(Permission.KNOWLEDGE_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> list[KnowledgeDocumentResponse]:
    """List documents belonging to the authenticated tenant only."""

    tenant_id = _tenant_id(current_user)
    rows = db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.tenant_id == tenant_id)
        .order_by(KnowledgeDocument.created_at.desc())
    ).all()
    return [KnowledgeDocumentResponse.from_model(row) for row in rows]


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentResponse,
    summary="Get a knowledge document",
)
def get_document(
    document_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.KNOWLEDGE_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> KnowledgeDocumentResponse:
    """Return one document, rejecting cross-tenant access."""

    row = _load_document(db, current_user, document_id)
    return KnowledgeDocumentResponse.from_model(row)


@router.get(
    "/documents/{document_id}/download",
    summary="Download the stored document file",
)
def download_document(
    document_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.KNOWLEDGE_READ.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    """Stream the original file for a document the tenant owns."""

    row = _load_document(db, current_user, document_id)
    if not row.file_path or not Path(row.file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The stored file is no longer available.",
        )
    return FileResponse(
        path=row.file_path,
        filename=row.name,
        media_type="application/octet-stream",
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge document",
)
def remove_document(
    document_id: str,
    current_user: Annotated[
        User, Depends(require_permission(Permission.KNOWLEDGE_WRITE.value))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Delete a document, its chunks, and its vectors."""

    row = _load_document(db, current_user, document_id)
    path = row.file_path
    delete_document(session=db, document=row, vector_store=_vector_store())
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            # The database record is already gone; a stale file is not fatal.
            pass
