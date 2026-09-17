"""MCP client that connects to the helpdesk AI agent MCP server."""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    """Connect to the MCP server and call get_job."""
    # Optional job_id can be passed as the first command-line argument.
    job_id = sys.argv[1] if len(sys.argv) > 1 else "job-1"

    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server.server"],
        cwd=".",
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                await session.initialize()

                # List available tools
                print("Discovering available tools...")
                tools_result = await session.list_tools()
                print(f"Available tools: {[tool.name for tool in tools_result.tools]}")

                if not tools_result.tools:
                    print("No tools available on the server.")
                    return

                # Call get_job with the requested job ID
                print(f"\nCalling get_job with job_id='{job_id}'...")
                result = await session.call_tool(
                    "get_job", arguments={"job_id": job_id}
                )

                print("Result:")
                for content in result.content:
                    if hasattr(content, "text"):
                        print(content.text)

                # Test with a non-existent job to show the controlled error path
                print("\nCalling get_job with job_id='job-does-not-exist'...")
                result = await session.call_tool(
                    "get_job", arguments={"job_id": "job-0a39bbc2e6f8427aa8e68c2642163"}
                )

                print("Result:")
                for content in result.content:
                    if hasattr(content, "text"):
                        print(content.text)

    except Exception as e:
        print(f"Error connecting to MCP server: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
