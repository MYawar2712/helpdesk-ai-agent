"""Tenant-filtered knowledge retrieval for the Day 8 Support Agent.

Retrieval is kept separate from generation. This module only returns relevant
chunks; the Support Agent decides how to use them.

Every entry point takes ``tenant_id`` from authenticated server context, never
from the customer message or model output, and applies a ``WHERE tenant_id = ?``
style filter in SQL for the keyword path.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from agents.tools.support_tools import KnowledgeChunk
from rag.tenant_store import TenantVectorStore

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "i",
        "my",
        "me",
        "you",
        "your",
        "we",
        "our",
        "it",
        "this",
        "that",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "for",
        "with",
        "be",
        "can",
        "could",
        "would",
        "please",
        "help",
        "need",
        "want",
        "how",
        "what",
        "when",
        "where",
        "why",
    }
)


class TenantChunkSource(Protocol):
    """Relational source of ready chunks for a tenant."""

    def keyword_search(
        self, tenant_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]: ...


class TenantKnowledgeRetriever:
    """Tenant-isolated retriever used by the Day 7 Support Agent.

    Satisfies the :class:`~agents.tools.support_tools.KnowledgeRetriever`
    protocol but additionally requires a ``tenant_id`` on every call, so a
    cross-tenant retrieval cannot be expressed at all.
    """

    def __init__(
        self,
        *,
        vector_store: TenantVectorStore | None = None,
        source: TenantChunkSource | None = None,
        source_factory: Any | None = None,
        top_k: int = 5,
    ) -> None:
        self._vector_store = vector_store
        self._source = source
        #: Preferred over ``source``: a callable returning a fresh chunk source
        #: per query, because SQLAlchemy sessions are not thread-safe and this
        #: retriever is shared across request threads. Any session opened by the
        #: factory is closed after the query so the pool is not exhausted.
        self._source_factory = source_factory
        self._top_k = top_k

    def _resolve_source(self) -> TenantChunkSource | None:
        if self._source_factory is not None:
            try:
                return self._source_factory()
            except Exception:  # noqa: BLE001 - degrade to no keyword results
                return None
        return self._source

    def retrieve_for_tenant(
        self, tenant_id: str | None, query: str, *, limit: int | None = None
    ) -> list[KnowledgeChunk]:
        """Return tenant-scoped chunks for *query*.

        A missing tenant yields no results rather than falling back to
        unscoped data. This is the isolation guarantee.
        """

        if not tenant_id or not query or not query.strip():
            return []
        top_k = limit or self._top_k

        if self._vector_store is not None:
            hits = self._vector_store.search(tenant_id, query, top_k=top_k)
            if hits:
                return [self._to_chunk(hit) for hit in hits]

        source = self._resolve_source()
        if source is None:
            return []
        try:
            rows = source.keyword_search(tenant_id, query, top_k)
        except Exception:  # noqa: BLE001 - retrieval must not break a turn
            return []
        finally:
            # The factory opened a dedicated session for this query; returning
            # the connection is what keeps concurrent retrieval safe.
            self._close_source(source)
        return [self._to_chunk(row) for row in rows]

    @staticmethod
    def _close_source(source: TenantChunkSource) -> None:
        """Release a factory-built source's session, best effort."""

        closer = getattr(source, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001 - cleanup must not break retrieval
                pass

    @staticmethod
    def _to_chunk(row: dict[str, Any]) -> KnowledgeChunk:
        metadata = row.get("metadata") or {}
        document_id = row.get("document_id") or metadata.get("document_id") or ""
        title = metadata.get("title") or metadata.get("name") or document_id
        return KnowledgeChunk(
            source=str(title),
            title=str(title),
            topic=str(metadata.get("topic", "general")),
            content=str(row.get("content", "")),
            score=float(metadata.get("score", 0.0)),
        )


def keyword_rank(query: str, content: str, *, title: str = "") -> float:
    """Score a chunk by token overlap, weighting the title more heavily."""

    def tokenize(text: str) -> set[str]:
        return {
            token
            for token in _TOKEN_RE.findall(text.lower())
            if token not in _STOPWORDS and len(token) > 2
        }

    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    body_tokens = tokenize(content)
    title_tokens = tokenize(title)
    score = len(query_tokens & body_tokens) + 2.0 * len(query_tokens & title_tokens)
    return score / len(query_tokens)
