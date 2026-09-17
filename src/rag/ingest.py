"""Ingest and search the local helpdesk knowledge base with Chroma."""

from __future__ import annotations

import re
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from llm.config import LLMConfig

DEFAULT_KNOWLEDGE_BASE = Path(__file__).resolve().parents[2] / "docs" / "knowledge_base"
DEFAULT_PERSIST_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "data" / "chroma_helpdesk"
)
EMBEDDING_MODEL = "qwen3.7-text-embedding"


def load_knowledge_articles(directory: Path = DEFAULT_KNOWLEDGE_BASE) -> list[Document]:
    """Load Markdown articles and attach stable source/topic metadata."""
    if not directory.is_dir():
        raise FileNotFoundError(f"Knowledge-base directory does not exist: {directory}")
    documents: list[Document] = []
    for path in sorted(directory.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        title = content.splitlines()[0].removeprefix("# ").strip()
        topic_match = re.search(r"^Topic:\s*(.+)$", content, re.MULTILINE)
        documents.append(
            Document(
                page_content=content,
                metadata={
                    "source": path.name,
                    "title": title,
                    "topic": topic_match.group(1).strip() if topic_match else "general",
                },
            )
        )
    if not documents:
        raise ValueError(f"No Markdown articles found in {directory}")
    return documents


def create_embedding_model(
    config: LLMConfig | None = None,
    *,
    model: str = EMBEDDING_MODEL,
) -> OpenAIEmbeddings:
    """Create the Qwen embedding client using the existing LLM API key."""
    runtime_config = config or LLMConfig.from_environment()
    return OpenAIEmbeddings(
        model=model,
        api_key=runtime_config.api_key,
        base_url=runtime_config.base_url,
    )


def ingest_knowledge_base(
    *,
    directory: Path = DEFAULT_KNOWLEDGE_BASE,
    persist_directory: Path = DEFAULT_PERSIST_DIRECTORY,
    embeddings: Embeddings | None = None,
    collection_name: str = "helpdesk_knowledge",
) -> Chroma:
    """Embed all articles and persist them in a local Chroma collection."""
    documents = load_knowledge_articles(directory)
    persist_directory.mkdir(parents=True, exist_ok=True)
    vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings or create_embedding_model(),
        persist_directory=str(persist_directory),
    )
    ids = [document.metadata["source"] for document in documents]
    vector_store.add_documents(documents, ids=ids)
    return vector_store


def search_knowledge_base(
    query: str,
    *,
    persist_directory: Path = DEFAULT_PERSIST_DIRECTORY,
    embeddings: Embeddings | None = None,
    k: int = 4,
    collection_name: str = "helpdesk_knowledge",
) -> list[Document]:
    """Return the most similar persisted knowledge-base articles."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if k < 1:
        raise ValueError("k must be greater than zero")
    vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings or create_embedding_model(),
        persist_directory=str(persist_directory),
    )
    return vector_store.similarity_search(query, k=k)


def keyword_search_knowledge_base(
    query: str,
    *,
    directory: Path = DEFAULT_KNOWLEDGE_BASE,
    k: int = 4,
) -> list[Document]:
    """Return locally matched articles when vector search is unavailable."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if k < 1:
        raise ValueError("k must be greater than zero")

    query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    scored_documents: list[tuple[int, Document]] = []
    for document in load_knowledge_articles(directory):
        haystack = " ".join(
            [
                document.page_content,
                str(document.metadata.get("title", "")),
                str(document.metadata.get("topic", "")),
            ]
        ).lower()
        article_terms = set(re.findall(r"[a-z0-9]+", haystack))
        score = len(query_terms & article_terms)
        if score:
            scored_documents.append((score, document))

    scored_documents.sort(key=lambda item: item[0], reverse=True)
    return [document for _, document in scored_documents[:k]]
