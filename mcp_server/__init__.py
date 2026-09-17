"""MCP server exposing helpdesk AI agent functionality."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project's ``src`` and root packages are importable before any
# submodule (e.g. ``mcp_server.server``) imports them.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
for _path in (str(SRC_PATH), str(PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
