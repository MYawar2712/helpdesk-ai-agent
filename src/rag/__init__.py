"""Retrieval-augmented generation foundations."""

from rag.ingest import (
    create_embedding_model,
    ingest_knowledge_base,
    load_knowledge_articles,
    search_knowledge_base,
)

__all__ = [
    "create_embedding_model",
    "ingest_knowledge_base",
    "load_knowledge_articles",
    "search_knowledge_base",
]
