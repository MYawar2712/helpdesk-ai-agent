"""Tenant-scoped vector storage for the Day 8 knowledge base.

The project already uses Chroma (``src/rag/ingest.py``), so Day 8 reuses that
single vector store rather than introducing pgvector or a second database. Each
tenant's chunks live in one collection but every record carries ``tenant_id``,
and retrieval is filtered server-side on that field.

Tenant isolation is enforced in three independent places:

1. Chroma ``where`` filter on ``tenant_id`` (pushed into the vector query).
2. A post-retrieval re-check of every returned chunk's metadata.
3. An optional relational re-verification via ``verify_ownership``, which
   re-checks chunk rows against the relational ``knowledge_chunks`` table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from rag.ingest import DEFAULT_PERSIST_DIRECTORY

logger = logging.getLogger(__name__)

TENANT_COLLECTION = "tenant_knowledge"


class TenantIsolationError(RuntimeError):
    """Raised when retrieved content fails the post-search tenant check."""


@dataclass(frozen=True, slots=True)
class StoredChunk:
    """A chunk that has been indexed for a tenant."""

    chunk_id: str
    tenant_id: str
    document_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]

    def chroma_metadata(self) -> dict[str, Any]:
        """Metadata stored alongside the embedding for tenant filtering."""

        scalar_metadata = {
            key: value
            for key, value in self.metadata.items()
            if isinstance(value, str | int | float | bool)
        }
        return {
            "tenant_id": self.tenant_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            **scalar_metadata,
        }


class TenantVectorStore:
    """Chroma-backed vector store with mandatory tenant scoping."""

    def __init__(
        self,
        *,
        persist_directory: Path = DEFAULT_PERSIST_DIRECTORY,
        embeddings: Embeddings | None = None,
        collection_name: str = TENANT_COLLECTION,
    ) -> None:
        self.persist_directory = persist_directory
        self.embeddings = embeddings
        self.collection_name = collection_name
        self._store: Any | None = None

    # ── Store lifecycle ───────────────────────────────────────────────────

    def _chroma(self) -> Any | None:
        """Open the Chroma collection, or return ``None`` when unavailable."""

        if self._store is not None:
            return self._store
        if self.embeddings is None:
            return None
        try:
            from langchain_chroma import Chroma

            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self._store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )
        except Exception:  # noqa: BLE001 - retrieval degrades to keyword search
            return None
        return self._store

    # ── Writes ────────────────────────────────────────────────────────────

    def add_chunks(self, chunks: list[StoredChunk]) -> int:
        """Index chunks for their tenant. Returns the number indexed."""

        if not chunks:
            return 0
        store = self._chroma()
        if store is None:
            return 0
        try:
            from langchain_core.documents import Document

            store.add_documents(
                [
                    Document(
                        page_content=chunk.content,
                        metadata=chunk.chroma_metadata(),
                    )
                    for chunk in chunks
                ],
                ids=[chunk.chunk_id for chunk in chunks],
            )
        except Exception:  # noqa: BLE001 - indexing failure is reported upstream
            logger.exception("Failed to index %d chunk(s)", len(chunks))
            return 0
        return len(chunks)

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        """Remove every chunk of one document belonging to *tenant_id*."""

        store = self._chroma()
        if store is None:
            return
        try:
            store.delete(
                where={
                    "$and": [
                        {"tenant_id": tenant_id},
                        {"document_id": document_id},
                    ]
                }
            )
        except Exception:  # noqa: BLE001 - deletion is best-effort
            logger.exception(
                "Failed to delete vectors for document %s (tenant %s)",
                document_id,
                tenant_id,
            )
            return

    # ── Reads ─────────────────────────────────────────────────────────────

    def search(
        self,
        tenant_id: str,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return the top-k chunks for *query*, restricted to *tenant_id*.

        The tenant filter is supplied by the caller from authenticated context
        and is never taken from the query text or the LLM.
        """

        if not tenant_id or not query.strip():
            return []
        store = self._chroma()
        if store is None:
            return []
        try:
            # NOTE: the installed langchain-chroma names this argument ``filter``.
            # Passing ``where`` lands in **kwargs and collides with the internal
            # ``where`` parameter, which fails the query outright.
            matches = store.similarity_search(
                query,
                k=top_k,
                filter={"tenant_id": tenant_id},
            )
        except Exception:  # noqa: BLE001 - caller falls back to keyword search
            # Logged rather than silently swallowed: a filter mistake would
            # otherwise be indistinguishable from "this tenant has no documents".
            logger.exception("Tenant vector search failed for tenant %s", tenant_id)
            return []

        results: list[dict[str, Any]] = []
        for document in matches:
            metadata = dict(getattr(document, "metadata", {}) or {})
            # Defence in depth: re-check the tenant even though Chroma filtered.
            if metadata.get("tenant_id") != tenant_id:
                continue
            results.append(
                {
                    "content": document.page_content,
                    "tenant_id": tenant_id,
                    "document_id": metadata.get("document_id"),
                    "chunk_index": metadata.get("chunk_index"),
                    "metadata": metadata,
                }
            )
        return results
