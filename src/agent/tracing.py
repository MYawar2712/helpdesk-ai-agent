"""Day 23: LangSmith tracing helpers for the helpdesk agent.

LangGraph node spans are emitted automatically when tracing env vars are set.
LLM calls go through a custom ``LLMClient`` (not a LangChain chat model), so
those methods are decorated with ``@traceable`` in ``llm.client`` and
``agent.rag_node``.

Environment variables (keep keys out of source):

    LANGCHAIN_TRACING_V2=true   (or LANGSMITH_TRACING=true)
    LANGCHAIN_API_KEY=<key>     (or LANGSMITH_API_KEY)
    LANGCHAIN_PROJECT=helpdesk-ai-agent
"""

from __future__ import annotations

import os
from typing import Any

try:
    from langsmith import traceable  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover

    def traceable(func=None, *, name: str = "", **_: Any):  # type: ignore[misc]
        """No-op shim used when langsmith is not installed."""
        if func is None:

            def decorator(f):
                return f

            return decorator
        return func


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def tracing_is_configured() -> bool:
    """Return True when a tracing flag and an API key are both present."""
    tracing_enabled = _env_enabled("LANGCHAIN_TRACING_V2") or _env_enabled(
        "LANGSMITH_TRACING"
    )
    api_key = (
        os.getenv("LANGCHAIN_API_KEY", "").strip()
        or os.getenv("LANGSMITH_API_KEY", "").strip()
    )
    return tracing_enabled and bool(api_key)


def tracing_project() -> str:
    """Return the active LangSmith project name."""
    return (
        os.getenv("LANGCHAIN_PROJECT", "").strip()
        or os.getenv("LANGSMITH_PROJECT", "").strip()
        or "helpdesk-ai-agent"
    )


def configure_tracing() -> bool:
    """Return True and print status when LangSmith tracing is active.

    LangChain / LangGraph reads these env-vars automatically:
        LANGCHAIN_TRACING_V2=true
        LANGCHAIN_API_KEY=<key>
        LANGCHAIN_PROJECT=<project>  (optional)

    LANGSMITH_TRACING / LANGSMITH_API_KEY / LANGSMITH_PROJECT are also accepted.

    Returns
    -------
    bool
        True when tracing is enabled, False when it is not configured.
    """
    tracing_enabled = _env_enabled("LANGCHAIN_TRACING_V2") or _env_enabled(
        "LANGSMITH_TRACING"
    )
    api_key = (
        os.getenv("LANGCHAIN_API_KEY", "").strip()
        or os.getenv("LANGSMITH_API_KEY", "").strip()
    )
    project = tracing_project()

    if tracing_enabled and api_key:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", project)
        print(f"[LangSmith] Tracing ENABLED  ->  project: {project!r}")
        return True

    if tracing_enabled and not api_key:
        print(
            "[LangSmith] Tracing is requested but LANGCHAIN_API_KEY / "
            "LANGSMITH_API_KEY is not set. Traces will NOT be sent."
        )
    else:
        print("[LangSmith] Tracing DISABLED (set LANGCHAIN_TRACING_V2=true to enable)")
    return False


def attach_run_metadata(metadata: dict[str, Any] | None) -> None:
    """Attach case metadata to the current LangSmith run, if one exists."""
    if not metadata:
        return
    try:
        from langsmith.run_helpers import get_current_run_tree
    except ImportError:
        return

    run = get_current_run_tree()
    if run is None:
        return

    payload = {str(key): value for key, value in metadata.items() if value is not None}
    existing = getattr(run, "metadata", None)
    if isinstance(existing, dict):
        existing.update(payload)
        return
    try:
        run.metadata = payload
    except Exception:
        return


def current_run_url() -> str | None:
    """Return the LangSmith UI URL for the current run, if available."""
    try:
        from langsmith.run_helpers import get_current_run_tree
    except ImportError:
        return None
    run = get_current_run_tree()
    if run is None:
        return None
    url = getattr(run, "get_url", None)
    if callable(url):
        try:
            return str(url())
        except Exception:
            return None
    return getattr(run, "url", None)


@traceable(name="helpdesk_agent_run")
def wrap_agent_run(
    agent: Any,
    ticket_text: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Invoke *agent* inside a named LangSmith run.

    Parameters
    ----------
    agent:
        A ``HelpdeskAgent`` (or any object with an ``.invoke(str)`` method).
    ticket_text:
        The support message to process.
    metadata:
        Optional dict attached to the trace (case_type, expected_route, etc.).
        LangSmith surfaces this in the run's metadata panel.

    Returns
    -------
    AgentState
        The raw state dict returned by the graph.
    """
    attach_run_metadata(metadata)
    return agent.invoke(ticket_text)
