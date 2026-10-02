"""Support Agent tools and the knowledge-retrieval interface.

RAG proper (embeddings + vector store) lands in Day 8. Day 7 only needs a *clean
interface*, so this module defines the :class:`KnowledgeRetriever` protocol that
Day 8's vector-backed retriever must satisfy, plus a deterministic keyword
implementation over ``docs/knowledge_base`` so the Support Agent is functional
today and can be swapped without touching the agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agents.context import AgentContext
from agents.tools.base import HUMAN, JOB, SUPPORT, ToolRegistry

_READ_SCOPE = frozenset({SUPPORT, JOB, HUMAN})

#: Default location of the markdown knowledge base.
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "docs" / "knowledge_base"

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

#: Curated support policy answers that do not require document retrieval.
_SUPPORT_INFORMATION: dict[str, str] = {
    "hours": (
        "Support is available Monday to Friday, 08:00-18:00, and Saturday "
        "09:00-13:00. Urgent safety issues are escalated to a human immediately."
    ),
    "channels": (
        "You can reach us through this chat, or by phone during support hours. "
        "A human specialist is assigned for billing disputes and safety issues."
    ),
    "services": (
        "We provide heating, cooling and HVAC, plumbing, electrical, and "
        "sanitary services, including installation, repair, and maintenance."
    ),
}


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """A single retrieved knowledge-base passage."""

    source: str
    title: str
    topic: str
    content: str
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "topic": self.topic,
            "content": self.content,
            "score": round(self.score, 4),
        }


class KnowledgeRetriever(Protocol):
    """Interface the Day 8 RAG retriever must implement."""

    def retrieve(self, query: str, *, limit: int = 3) -> list[KnowledgeChunk]: ...


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 2
    }


class KeywordKnowledgeRetriever:
    """Deterministic keyword retriever over the markdown knowledge base.

    Intentionally simple: Day 8 replaces this with the embedding-backed
    :class:`agent.rag_node.RAGRetriever` without changing any caller.
    """

    def __init__(self, knowledge_dir: Path | None = None) -> None:
        self.knowledge_dir = knowledge_dir or DEFAULT_KNOWLEDGE_DIR
        self._documents: list[KnowledgeChunk] | None = None

    def _load(self) -> list[KnowledgeChunk]:
        if self._documents is not None:
            return self._documents

        documents: list[KnowledgeChunk] = []
        if self.knowledge_dir.is_dir():
            for path in sorted(self.knowledge_dir.glob("*.md")):
                try:
                    raw = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                title_match = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
                topic_match = re.search(r"^Topic:\s*(.+)$", raw, re.MULTILINE)
                documents.append(
                    KnowledgeChunk(
                        source=path.name,
                        title=(
                            title_match.group(1).strip()
                            if title_match
                            else path.stem.replace("_", " ")
                        ),
                        topic=(
                            topic_match.group(1).strip().lower()
                            if topic_match
                            else "general"
                        ),
                        content=raw.strip(),
                    )
                )
        self._documents = documents
        return documents

    def retrieve(self, query: str, *, limit: int = 3) -> list[KnowledgeChunk]:
        """Return the best-scoring knowledge chunks for *query*."""

        documents = self._load()
        if not documents:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[KnowledgeChunk] = []
        for document in documents:
            title_tokens = _tokenize(document.title)
            body_tokens = _tokenize(document.content)
            # Title matches are weighted more heavily than body matches.
            score = 2.0 * len(query_tokens & title_tokens) + 1.0 * len(
                query_tokens & body_tokens
            )
            if score <= 0:
                continue
            scored.append(
                KnowledgeChunk(
                    source=document.source,
                    title=document.title,
                    topic=document.topic,
                    content=document.content,
                    score=score / len(query_tokens),
                )
            )

        scored.sort(key=lambda chunk: chunk.score, reverse=True)
        return scored[:limit]


def search_knowledge(
    retriever: KnowledgeRetriever,
    ctx: AgentContext,
    query: str,
    limit: int = 3,
) -> dict[str, Any]:
    """Search the knowledge base for support answers.

    Knowledge retrieval is read-only and tenant-agnostic, so no ownership check
    applies; the customer's own records are never included in results.
    """

    if not query or not query.strip():
        return {"found": False, "chunks": [], "message": "No search query provided."}

    chunks = retriever.retrieve(query, limit=limit)
    if not chunks:
        return {
            "found": False,
            "chunks": [],
            "message": (
                "No knowledge base article matched that question. Consider "
                "escalating to a human specialist."
            ),
        }
    return {
        "found": True,
        "chunks": [chunk.as_dict() for chunk in chunks],
        "message": f"Found {len(chunks)} relevant knowledge base article(s).",
    }


def get_support_information(ctx: AgentContext, topic: str = "hours") -> dict[str, Any]:
    """Return curated support policy information (hours, channels, services)."""

    key = (topic or "hours").strip().lower()
    value = _SUPPORT_INFORMATION.get(key)
    if value is None:
        return {
            "found": False,
            "topic": key,
            "available_topics": sorted(_SUPPORT_INFORMATION),
            "message": f"No support information is available for '{key}'.",
        }
    return {"found": True, "topic": key, "information": value, "message": value}


def register_support_tools(
    registry: ToolRegistry, retriever: KnowledgeRetriever
) -> ToolRegistry:
    """Register Support Agent tools using *retriever* for knowledge search."""

    registry.add(
        "search_knowledge",
        "Search the support knowledge base for FAQs and troubleshooting guides.",
        lambda ctx, query, limit=3: search_knowledge(retriever, ctx, query, limit),
        scope=_READ_SCOPE,
        required_arguments=("query",),
    )
    registry.add(
        "get_support_information",
        "Get support policy information such as opening hours, contact "
        "channels, or the list of services offered.",
        lambda ctx, topic="hours": get_support_information(ctx, topic),
        scope=_READ_SCOPE,
    )
    return registry
