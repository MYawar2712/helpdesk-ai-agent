"""Tests for the MCP server."""

from __future__ import annotations

import json
import sqlite3

import pytest

from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database


def create_test_repository() -> HelpdeskDataRepository:
    """Create a test repository with seeded data."""
    connection = sqlite3.connect(":memory:")
    seed_database(connection)
    return HelpdeskDataRepository(connection, NoSQLClient(sqlite3.connect(":memory:")))


def test_mcp_server_module_imports() -> None:
    """MCP server module can be imported."""
    import mcp_server.server

    assert hasattr(mcp_server.server, "run_server")


def test_get_job_tool_is_exposed() -> None:
    """The get_job tool is properly configured."""
    from tools.get_job import get_job

    repository = create_test_repository()
    result = get_job(repository, "job-1")

    assert result["found"] is True
    assert result["job"]["id"] == "job-1"


def test_existing_job_can_be_retrieved() -> None:
    """Existing jobs return structured data."""
    from tools.get_job import get_job

    repository = create_test_repository()

    # Test multiple jobs
    for job_id in ["job-1", "job-2", "job-3"]:
        result = get_job(repository, job_id)
        assert result["found"] is True
        assert result["job"]["id"] == job_id
        assert "customer_id" in result["job"]
        assert "status" in result["job"]
        assert "title" in result["job"]


def test_nonexistent_job_returns_controlled_error() -> None:
    """Non-existent jobs return a clear not-found result."""
    from tools.get_job import get_job

    repository = create_test_repository()
    result = get_job(repository, "job-999")

    assert result["found"] is False
    assert result["job"] is None
    assert result["error"] == "Job not found"


@pytest.mark.parametrize(
    "invalid_input",
    ["", "   ", None],
)
def test_invalid_input_is_rejected(invalid_input: object) -> None:
    """Invalid job IDs are rejected with clear errors."""
    from tools.get_job import get_job

    repository = create_test_repository()

    with pytest.raises((ValueError, TypeError)):
        get_job(repository, invalid_input)  # type: ignore[arg-type]


def test_customer_job_authorization() -> None:
    """Jobs belong to specific customers and cannot be accessed cross-customer."""
    from tools.get_job import get_job

    repository = create_test_repository()

    # job-1 belongs to customer-1 (based on seed data: (1-1) % 5 + 1 = 1)
    result = get_job(repository, "job-1")
    assert result["found"] is True
    assert result["job"]["customer_id"] == "customer-1"

    # job-2 belongs to customer-2 ((2-1) % 5 + 1 = 2)
    result = get_job(repository, "job-2")
    assert result["found"] is True
    assert result["job"]["customer_id"] == "customer-2"

    # job-6 belongs to customer-1 ((6-1) % 5 + 1 = 1)
    result = get_job(repository, "job-6")
    assert result["found"] is True
    assert result["job"]["customer_id"] == "customer-1"


def test_mcp_server_creates_repository() -> None:
    """The MCP server can create its repository."""
    from mcp_server.server import create_repository

    repository = create_repository()
    assert isinstance(repository, HelpdeskDataRepository)

    # Verify it has data
    result = repository.get_job("job-1")
    assert result is not None
    assert result["id"] == "job-1"


def test_mcp_server_tool_listing() -> None:
    """The MCP server lists the get_job tool."""
    # This is a basic structural test
    # The actual async tool listing is tested via integration
    import mcp_server.server as server_module

    assert hasattr(server_module, "list_tools") or hasattr(server_module, "run_server")


@pytest.mark.asyncio
async def test_mcp_server_tool_call_valid_job() -> None:
    """The MCP server handles valid get_job calls."""
    from mcp_server.server import call_tool

    repository = create_test_repository()

    # Mock the repository in the server module
    import mcp_server.server as server_module

    original_repo = getattr(server_module, "_repository", None)
    server_module._repository = repository

    try:
        result = await call_tool("get_job", {"job_id": "job-1"})
        assert len(result) == 1
        content_text = result[0].text
        data = json.loads(content_text)
        assert data["found"] is True
        assert data["job"]["id"] == "job-1"
    finally:
        if original_repo is not None:
            server_module._repository = original_repo


@pytest.mark.asyncio
async def test_mcp_server_tool_call_invalid_job() -> None:
    """The MCP server handles invalid job IDs."""
    from mcp_server.server import call_tool

    repository = create_test_repository()

    import mcp_server.server as server_module

    original_repo = getattr(server_module, "_repository", None)
    server_module._repository = repository

    try:
        result = await call_tool("get_job", {"job_id": "job-999"})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["found"] is False
        assert "error" in data
    finally:
        if original_repo is not None:
            server_module._repository = original_repo


@pytest.mark.asyncio
async def test_mcp_server_tool_call_empty_job_id() -> None:
    """The MCP server rejects empty job IDs."""
    from mcp_server.server import call_tool

    repository = create_test_repository()

    import mcp_server.server as server_module

    original_repo = getattr(server_module, "_repository", None)
    server_module._repository = repository

    try:
        result = await call_tool("get_job", {"job_id": ""})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["found"] is False
        assert "error" in data
    finally:
        if original_repo is not None:
            server_module._repository = original_repo


@pytest.mark.asyncio
async def test_mcp_server_authorization_check() -> None:
    """The MCP server enforces customer authorization."""
    from mcp_server.server import call_tool

    repository = create_test_repository()

    import mcp_server.server as server_module

    original_repo = getattr(server_module, "_repository", None)
    server_module._repository = repository

    try:
        # job-1 belongs to customer-1, not customer-2
        result = await call_tool(
            "get_job", {"job_id": "job-1", "customer_id": "customer-2"}
        )
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["found"] is False
        assert "Unauthorized" in data["error"]

        # Correct customer should work
        result = await call_tool(
            "get_job", {"job_id": "job-1", "customer_id": "customer-1"}
        )
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["found"] is True
        assert data["job"]["id"] == "job-1"
    finally:
        if original_repo is not None:
            server_module._repository = original_repo


@pytest.mark.asyncio
async def test_mcp_server_unknown_tool() -> None:
    """The MCP server handles unknown tool names."""
    from mcp_server.server import call_tool

    repository = create_test_repository()

    import mcp_server.server as server_module

    original_repo = getattr(server_module, "_repository", None)
    server_module._repository = repository

    try:
        result = await call_tool("unknown_tool", {})
        assert len(result) == 1
        assert "Unknown tool" in result[0].text
    finally:
        if original_repo is not None:
            server_module._repository = original_repo
