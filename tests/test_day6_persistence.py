"""Day 6 tests for persistent LangGraph conversation state."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TypedDict
from unittest.mock import Mock

import pytest
from langgraph.graph import END, START, StateGraph

from agent.checkpointer import (
    CheckpointStateError,
    CheckpointUnavailableError,
    open_persistent_checkpointer,
)
from agent.graph import HelpdeskAgent
from db.conversation_repository import ConversationRepository
from db.seed import seed_database


class _MemoryState(TypedDict, total=False):
    message: str
    messages: list[str]


def _append_message(state: _MemoryState) -> _MemoryState:
    return {
        "messages": [*state.get("messages", []), state["message"]],
    }


def _memory_graph(checkpointer):
    graph = StateGraph(_MemoryState)
    graph.add_node("append", _append_message)
    graph.add_edge(START, "append")
    graph.add_edge("append", END)
    return graph.compile(checkpointer=checkpointer)


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _config(conversation_id: str) -> dict:
    return {"configurable": {"thread_id": conversation_id}}


def _mock_client(response: str) -> Mock:
    client = Mock()
    client.generate_json.return_value = {
        "route": "respond",
        "response": response,
    }
    client.generate.return_value = response
    return client


def test_checkpoint_survives_graph_recreation(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "langgraph-checkpoints.sqlite3"
    config = _config("conversation-1")

    with open_persistent_checkpointer(_sqlite_url(checkpoint_path)) as saver:
        graph = _memory_graph(saver)
        graph.invoke({"message": "first message"}, config=config)
        assert graph.get_state(config).values["messages"] == ["first message"]

    # A new saver and compiled graph represent an application restart.
    with open_persistent_checkpointer(_sqlite_url(checkpoint_path)) as saver:
        graph = _memory_graph(saver)
        restored = graph.get_state(config).values
        assert restored["messages"] == ["first message"]

        graph.invoke({"message": "second message"}, config=config)
        assert graph.get_state(config).values["messages"] == [
            "first message",
            "second message",
        ]


def test_same_conversation_id_resumes_same_state(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "langgraph-checkpoints.sqlite3"
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    conversation_repo = ConversationRepository(connection)
    url = _sqlite_url(checkpoint_path)

    try:
        with open_persistent_checkpointer(url) as saver:
            agent = HelpdeskAgent(
                llm_client=_mock_client("first answer"),
                tools=[],
                conversation_repo=conversation_repo,
                checkpointer=saver,
            )
            agent.invoke(
                "Tell me about my first request.",
                customer_id="customer-1",
                email_thread_id="conversation-1",
            )
            first_state = agent.graph.get_state(_config("conversation-1")).values
            assert first_state["final_response"] == "first answer"

        with open_persistent_checkpointer(url) as saver:
            agent = HelpdeskAgent(
                llm_client=_mock_client("second answer"),
                tools=[],
                conversation_repo=conversation_repo,
                checkpointer=saver,
            )
            restored = agent.graph.get_state(_config("conversation-1")).values
            assert restored["final_response"] == "first answer"

            result = agent.invoke(
                "Now answer my follow-up.",
                customer_id="customer-1",
                email_thread_id="conversation-1",
            )
            assert result["final_response"] == "second answer"
            assert "Tell me about my first request." in str(
                agent.graph.get_state(_config("conversation-1")).values[
                    "conversation_history"
                ]
            )
    finally:
        connection.close()


def test_new_conversation_has_independent_checkpoint(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "langgraph-checkpoints.sqlite3"

    with open_persistent_checkpointer(_sqlite_url(checkpoint_path)) as saver:
        graph = _memory_graph(saver)
        graph.invoke({"message": "conversation A"}, config=_config("a"))
        graph.invoke({"message": "conversation B"}, config=_config("b"))

        assert graph.get_state(_config("a")).values["messages"] == ["conversation A"]
        assert graph.get_state(_config("b")).values["messages"] == ["conversation B"]


def test_unknown_thread_has_no_checkpoint_state(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "langgraph-checkpoints.sqlite3"

    with open_persistent_checkpointer(_sqlite_url(checkpoint_path)) as saver:
        graph = _memory_graph(saver)
        snapshot = graph.get_state(_config("not-created"))

        assert snapshot.values == {}


def test_broken_checkpoint_store_raises_typed_error(tmp_path: Path) -> None:
    """A corrupt checkpoint database must raise, not silently reset the thread."""
    checkpoint_path = tmp_path / "broken.sqlite3"
    checkpoint_path.write_bytes(b"this is not a sqlite database")

    with pytest.raises(CheckpointUnavailableError):
        with open_persistent_checkpointer(_sqlite_url(checkpoint_path)) as saver:
            graph = _memory_graph(saver)
            graph.invoke({"message": "hello"}, config=_config("conversation-1"))


def test_caller_errors_are_not_misreported_as_checkpoint_failures() -> None:
    """Application errors inside the context must keep their own type."""

    class AppError(Exception):
        pass

    with pytest.raises(AppError, match="boom"):
        with open_persistent_checkpointer("sqlite:///:memory:"):
            raise AppError("boom")


def test_foreign_thread_id_does_not_fork_a_second_checkpoint(
    tmp_path: Path,
) -> None:
    """With checkpointing on, a mismatched thread id must never fork a thread."""
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    conversation_repo = ConversationRepository(connection)

    try:
        with open_persistent_checkpointer(
            _sqlite_url(tmp_path / "langgraph-checkpoints.sqlite3")
        ) as saver:
            agent = HelpdeskAgent(
                llm_client=_mock_client("owner answer"),
                tools=[],
                conversation_repo=conversation_repo,
                checkpointer=saver,
            )
            agent.invoke(
                "Owner question.",
                customer_id="customer-1",
                email_thread_id="shared-thread",
            )

            # A different customer presenting the same thread id is rejected
            # rather than silently continuing (or forking) the thread.
            with pytest.raises(CheckpointStateError):
                agent.invoke(
                    "Intruder question.",
                    customer_id="customer-2",
                    email_thread_id="shared-thread",
                )

            # The canonical thread is untouched by the rejected attempt.
            values = agent.graph.get_state(_config("shared-thread")).values
            assert values["customer_id"] == "customer-1"
            assert "Intruder question." not in str(values)
    finally:
        connection.close()
