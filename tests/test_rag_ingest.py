from __future__ import annotations

from pathlib import Path

from langchain_core.embeddings import Embeddings

from llm.config import LLMConfig
from rag.ingest import (
    EMBEDDING_MODEL,
    create_embedding_model,
    ingest_knowledge_base,
    load_knowledge_articles,
    search_knowledge_base,
)


class FakeEmbeddings(Embeddings):
    """Small deterministic embedding model for offline vector-store tests."""

    terms = ("cooling", "invoice", "warranty", "appointment", "safety")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        return [float(lowered.count(term)) for term in self.terms]


def test_loads_articles_with_useful_metadata() -> None:
    articles = load_knowledge_articles()

    assert len(articles) >= 18
    assert articles[0].metadata["source"].endswith(".md")
    assert articles[0].metadata["title"]
    assert articles[0].metadata["topic"]


def test_ingestion_persists_articles_and_similarity_search_retrieves_match(
    tmp_path: Path,
) -> None:
    embeddings = FakeEmbeddings()
    ingest_knowledge_base(
        persist_directory=tmp_path / "chroma",
        embeddings=embeddings,
    )

    results = search_knowledge_base(
        "The customer was charged twice on an invoice.",
        persist_directory=tmp_path / "chroma",
        embeddings=embeddings,
        k=3,
    )

    assert len(results) == 3
    assert any("duplicate_charge.md" == result.metadata["source"] for result in results)


def test_embedding_model_uses_requested_qwen_model_and_runtime_config() -> None:
    model = create_embedding_model(
        LLMConfig(
            api_key="test-key",
            model="qwen-flash",
            base_url="https://example.test/v1",
        )
    )

    assert model.model == EMBEDDING_MODEL
    assert model.openai_api_key.get_secret_value() == "test-key"
    assert str(model.openai_api_base).rstrip("/") == "https://example.test/v1"


def test_invalid_search_arguments_are_rejected(tmp_path: Path) -> None:
    ingest_knowledge_base(
        persist_directory=tmp_path / "chroma",
        embeddings=FakeEmbeddings(),
    )

    import pytest

    with pytest.raises(ValueError, match="must not be empty"):
        search_knowledge_base(
            " ", persist_directory=tmp_path / "chroma", embeddings=FakeEmbeddings()
        )
    with pytest.raises(ValueError, match="greater than zero"):
        search_knowledge_base(
            "invoice",
            persist_directory=tmp_path / "chroma",
            embeddings=FakeEmbeddings(),
            k=0,
        )
