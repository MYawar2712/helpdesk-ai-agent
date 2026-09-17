"""MCP server exposing get_job functionality."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from clients.nosql_client import NoSQLClient
from db.data_layer import HelpdeskDataRepository
from db.seed import seed_database
from mcp_server import PROJECT_ROOT
from tools.get_job import get_job as get_job_impl

# Global repository for the server
_repository: HelpdeskDataRepository | None = None


def create_repository() -> HelpdeskDataRepository:
    """Create a repository backed by the local database.

    Falls back to in-memory seed data when the local database file is absent
    (e.g. in a fresh checkout), so tests and demonstrations still work.
    """
    global _repository
    if _repository is not None:
        return _repository

    database_path = Path(PROJECT_ROOT) / "db" / "helpdesk.sqlite3"
    if database_path.exists():
        connection = sqlite3.connect(str(database_path))
    else:
        connection = sqlite3.connect(":memory:")
        seed_database(connection)

    _repository = HelpdeskDataRepository(
        connection, NoSQLClient(sqlite3.connect(":memory:"))
    )
    return _repository


# Create the MCP server
mcp = MCPServer("helpdesk-ai-agent")


@mcp.tool()
def get_job(job_id: str, customer_id: str | None = None) -> str:
    """Get the status and details for one job using its ID.

    Args:
        job_id: The job ID to look up (e.g., 'job-1' or '1')
        customer_id: The customer ID for authorization (optional)

    Returns:
        JSON string with job information or error
    """
    repository = create_repository()

    if not job_id or not isinstance(job_id, str):
        return json.dumps(
            {"found": False, "job": None, "error": "job_id must be a non-empty string"}
        )

    try:
        result = get_job_impl(repository, job_id)
    except ValueError as e:
        return json.dumps({"found": False, "job": None, "error": str(e)})

    if not result["found"]:
        return json.dumps({"found": False, "job": None, "error": "Job not found"})

    job = result["job"]

    # Authorization check
    if customer_id and job.get("customer_id") != customer_id:
        return json.dumps(
            {
                "found": False,
                "job": None,
                "error": "Unauthorized: job does not belong to the specified customer",
            }
        )

    return json.dumps(result)


async def list_tools() -> list[Any]:
    """List available tools (for testing)."""
    from mcp.types import Tool

    return [
        Tool(
            name="get_job",
            description=get_job.__doc__ or "Get job details",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "customer_id": {"type": "string"},
                },
                "required": ["job_id"],
            },
        )
    ]


async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Call a tool (for testing)."""
    from mcp.types import TextContent

    if name != "get_job":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    result_text = get_job(**arguments)
    return [TextContent(type="text", text=result_text)]


def run_server() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run_server()
