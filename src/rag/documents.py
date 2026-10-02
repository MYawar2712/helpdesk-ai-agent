"""Tenant knowledge-document processing pipeline.

Status flow::

    PENDING -> PROCESSING -> READY
                        \\-> FAILED

Processing is deliberately synchronous and modular so the extract/chunk/embed
stages can be moved to a Celery worker later without changing callers. Errors
are recorded as short, safe messages; stack traces are never persisted or
returned through the API.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agent.rag_node import chunk_documents
from db.models import KnowledgeChunk, KnowledgeDocument
from rag.retrieval import keyword_rank
from rag.tenant_store import StoredChunk, TenantVectorStore

logger = logging.getLogger(__name__)

#: Documents larger than this are rejected rather than truncated.
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024

ALLOWED_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})


class DocumentStatus(StrEnum):
    """Explicit processing states for a knowledge document."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DocumentProcessingError(RuntimeError):
    """Raised when a document cannot be processed. Message is API-safe."""


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    """Result of a successful processing run."""

    document_id: str
    chunk_count: int
    indexed: int


def _read_text(path: Path) -> str:
    """Extract plain text from a supported document."""

    if not path.exists() or not path.is_file():
        raise DocumentProcessingError("The uploaded file could not be read.")
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise DocumentProcessingError("The document is too large to process.")
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentProcessingError(
            "Unsupported file type. Upload a .md, .txt, .html, or .htm file."
        )
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise DocumentProcessingError("The uploaded file could not be read.") from error
    if suffix in {".html", ".htm"}:
        raw = re.sub(r"<[^>]+>", " ", raw)
    text = raw.strip()
    if not text:
        raise DocumentProcessingError("The document contains no readable text.")
    return text


def _chunk_text(
    text: str, *, name: str, tenant_id: str, document_id: str
) -> list[StoredChunk]:
    """Split text into chunks and attach tenant metadata."""

    from langchain_core.documents import Document

    pieces = chunk_documents(
        [Document(page_content=text, metadata={"title": name})],
        chunk_size=900,
        chunk_overlap=120,
    )
    chunks: list[StoredChunk] = []
    for index, piece in enumerate(pieces):
        metadata: dict[str, Any] = {
            "title": name,
            "tenant_id": tenant_id,
            "document_id": document_id,
        }
        metadata.update(piece.metadata or {})
        chunks.append(
            StoredChunk(
                chunk_id=f"{document_id}:{index}",
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=index,
                content=piece.page_content,
                metadata=metadata,
            )
        )
    return chunks


def process_document(
    *,
    session: Session,
    document: KnowledgeDocument,
    vector_store: TenantVectorStore | None = None,
) -> ProcessedDocument:
    """Run the full pipeline for one document and mark it READY or FAILED."""

    document.processing_status = DocumentStatus.PROCESSING.value
    session.commit()

    try:
        path = Path(document.file_path or "")
        text = _read_text(path)
        chunks = _chunk_text(
            text,
            name=document.name,
            tenant_id=document.tenant_id,
            document_id=document.id,
        )
        if not chunks:
            raise DocumentProcessingError("The document produced no content.")

        session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document.id,
                KnowledgeChunk.tenant_id == document.tenant_id,
            )
        )
        rows = [
            KnowledgeChunk(
                id=chunk.chunk_id,
                tenant_id=chunk.tenant_id,
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                chunk_metadata=chunk.metadata,
            )
            for chunk in chunks
        ]
        session.add_all(rows)

        indexed = 0
        if vector_store is not None:
            indexed = vector_store.add_chunks(chunks)

        metadata = dict(document.doc_metadata or {})
        metadata.update({"chunk_count": len(chunks), "indexed": indexed})
        document.doc_metadata = metadata
        document.processing_status = DocumentStatus.READY.value
        session.commit()
        return ProcessedDocument(
            document_id=document.id, chunk_count=len(chunks), indexed=indexed
        )
    except Exception as error:  # noqa: BLE001 - status must reflect the failure
        logger.warning("Document processing failed for %s: %s", document.id, error)
        document.processing_status = DocumentStatus.FAILED.value
        metadata = dict(document.doc_metadata or {})
        # Store a short, safe reason rather than a stack trace.
        metadata["error"] = (
            str(error)[:200]
            if isinstance(error, DocumentProcessingError)
            else "Document processing failed."
        )
        document.doc_metadata = metadata
        session.commit()
        if isinstance(error, DocumentProcessingError):
            raise
        raise DocumentProcessingError("Document processing failed.") from error


def delete_document(
    *,
    session: Session,
    document: KnowledgeDocument,
    vector_store: TenantVectorStore | None = None,
) -> None:
    """Delete a document, its chunks, and its vectors."""

    if vector_store is not None:
        vector_store.delete_document(document.tenant_id, document.id)
    session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document.id,
            KnowledgeChunk.tenant_id == document.tenant_id,
        )
    )
    session.delete(document)
    session.commit()


class RelationalChunkSource:
    """Tenant-scoped keyword search over ready documents' chunks."""

    def __init__(self, session: Session, *, owns_session: bool = False) -> None:
        self._session = session
        #: True when this source created the session and must close it.
        self._owns_session = owns_session

    def close(self) -> None:
        """Return the session to the pool when this source owns it.

        Retrieval runs per request; an unclosed session would slowly consume the
        whole connection pool under concurrent load.
        """

        if self._owns_session:
            self._session.close()
            self._owns_session = False

    def keyword_search(
        self, tenant_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        rows = self._session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.processing_status == DocumentStatus.READY.value,
            )
        ).all()
        if not rows:
            return []

        scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
        for chunk, document in rows:
            metadata = dict(chunk.chunk_metadata or {})
            score = keyword_rank(
                query, chunk.content, title=str(metadata.get("title") or document.name)
            )
            if score > 0:
                scored.append((score, chunk, document))
        scored.sort(key=lambda item: item[0], reverse=True)

        results: list[dict[str, Any]] = []
        for score, chunk, document in scored[:limit]:
            metadata = dict(chunk.chunk_metadata or {})
            metadata.update({"title": document.name, "score": score})
            results.append(
                {
                    "content": chunk.content,
                    "tenant_id": chunk.tenant_id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "metadata": metadata,
                }
            )
        return results
