"""Day 19 RAG Pipeline, Chunking, Context Injection, and Grounding Self-Check."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.tracing import traceable
from llm.client import LLMClient
from rag.ingest import (
    DEFAULT_PERSIST_DIRECTORY,
    search_knowledge_base,
)

SAFE_FALLBACK_RESPONSE = (
    "I'm sorry, but I don't have enough information in the knowledge base to answer "
    "your question accurately. Please contact human support for assistance."
)


@dataclass
class RAGResult:
    """Structure returned by the RAG node pipeline."""

    query: str
    retrieved_chunks: list[Document]
    candidate_answer: str
    is_grounded: bool
    grounding_reason: str
    final_response: str
    is_fallback: bool


class LLMProtocol(Protocol):
    """Protocol for LLM interactions in RAG generation and grounding self-check."""

    def generate(self, system_prompt: str, user_prompt: str) -> str: ...

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def chunk_documents(
    documents: list[Document],
    chunk_size: int = 400,
    chunk_overlap: int = 50,
) -> list[Document]:
    """Split documents into smaller chunks while preserving metadata."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(documents)


class RAGRetriever:
    """Responsibility: Vector search & retrieval of relevant knowledge chunks."""

    def __init__(
        self,
        *,
        persist_directory: Path = DEFAULT_PERSIST_DIRECTORY,
        embeddings: Embeddings | None = None,
        collection_name: str = "helpdesk_knowledge",
        k: int = 3,
    ) -> None:
        self.persist_directory = persist_directory
        self.embeddings = embeddings
        self.collection_name = collection_name
        self.k = k

    @traceable(name="rag_retrieve")
    def retrieve(self, query: str) -> list[Document]:
        """Retrieve relevant document chunks for the user query."""
        if not query.strip():
            return []

        try:
            chunks = search_knowledge_base(
                query=query,
                persist_directory=self.persist_directory,
                embeddings=self.embeddings,
                k=self.k,
                collection_name=self.collection_name,
            )
            return chunks
        except Exception:
            return []


class RAGGenerator:
    """Responsibility: Context injection & LLM answer generation."""

    def __init__(self, llm_client: LLMProtocol | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def format_context(self, chunks: list[Document]) -> str:
        """Format retrieved chunks for prompt context injection."""
        if not chunks:
            return "No relevant context found."

        context_parts = []
        for idx, doc in enumerate(chunks, 1):
            source = doc.metadata.get("source", f"doc_{idx}")
            title = doc.metadata.get("title", "Article")
            context_parts.append(
                f"[Source {idx}: {title} ({source})]\n{doc.page_content.strip()}"
            )
        return "\n\n".join(context_parts)

    @traceable(name="rag_generate")
    def generate_answer(self, query: str, chunks: list[Document]) -> str:
        """Inject context into prompt and generate answer using LLM."""
        context_str = self.format_context(chunks)
        system_prompt = (
            "You are a helpful technical support assistant for helpdesk. "
            "Answer the customer question strictly using ONLY the provided context. "
            "If context is insufficient, state that the knowledge base does "
            "not contain sufficient details."
        )
        user_prompt = f"Context:\n{context_str}\n\nCustomer Question:\n{query}"
        return self.llm_client.generate(system_prompt, user_prompt)


class GroundingChecker:
    """Responsibility: Self-check answer against context for factual grounding."""

    def __init__(self, llm_client: LLMProtocol | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    @traceable(name="rag_grounding_check")
    def check_grounding(
        self, query: str, chunks: list[Document], candidate_answer: str
    ) -> tuple[bool, str]:
        """Self-check whether candidate_answer is supported by context."""
        if not chunks or not candidate_answer.strip():
            return False, "Insufficient context or empty answer."

        context_str = "\n\n".join([doc.page_content for doc in chunks])
        system_prompt = (
            "You are a strict factual grounding verifier. Return JSON only.\n"
            "Analyze whether candidate answer is strictly supported by context.\n"
            "Return JSON object with keys:\n"
            '  "is_grounded": boolean (true if all facts supported, false otherwise)\n'
            '  "reason": string (explanation of decision)'
        )
        user_prompt = (
            f"Context:\n{context_str}\n\n"
            f"Customer Question:\n{query}\n\n"
            f"Candidate Answer:\n{candidate_answer}"
        )

        try:
            result = self.llm_client.generate_json(system_prompt, user_prompt)
            is_grounded = bool(result.get("is_grounded", False))
            reason = str(result.get("reason", "No reason provided."))
            return is_grounded, reason
        except Exception as err:
            return False, f"Grounding check failed: {err}"


class RAGNode:
    """Orchestrate Retrieval -> Context Injection -> Answer -> Grounding Check."""

    def __init__(
        self,
        retriever: RAGRetriever | None = None,
        generator: RAGGenerator | None = None,
        grounding_checker: GroundingChecker | None = None,
        *,
        fallback_response: str = SAFE_FALLBACK_RESPONSE,
    ) -> None:
        self.retriever = retriever or RAGRetriever()
        self.generator = generator or RAGGenerator()
        self.grounding_checker = grounding_checker or GroundingChecker()
        self.fallback_response = fallback_response

    @traceable(name="rag_pipeline")
    def run(self, query: str) -> RAGResult:
        """Execute the full RAG pipeline for a query.

        Grounding self-check is recorded for observability. When chunks are
        retrieved we always return the candidate answer; the grounding verdict
        is surfaced via ``is_grounded`` / ``grounding_reason`` so downstream
        callers can inspect it without silently suppressing valid answers.
        The hard fallback is reserved for the case where *no chunks at all*
        are retrieved from the knowledge base.
        """
        chunks = self.retriever.retrieve(query)
        if not chunks:
            return RAGResult(
                query=query,
                retrieved_chunks=[],
                candidate_answer="",
                is_grounded=False,
                grounding_reason="No relevant chunks retrieved from knowledge base.",
                final_response=self.fallback_response,
                is_fallback=True,
            )

        candidate_answer = self.generator.generate_answer(query, chunks)
        is_grounded, reason = self.grounding_checker.check_grounding(
            query, chunks, candidate_answer
        )

        # Grounding check is a soft warning: use the candidate answer when
        # chunks exist. Only fall back when there were no chunks to begin with.
        return RAGResult(
            query=query,
            retrieved_chunks=chunks,
            candidate_answer=candidate_answer,
            is_grounded=is_grounded,
            grounding_reason=reason,
            final_response=candidate_answer,
            is_fallback=False,
        )
