"""Test path configuration for the root-level database package."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

loaded_db = sys.modules.get("db")
if loaded_db is not None and not str(getattr(loaded_db, "__file__", "")).startswith(
    str(PROJECT_ROOT)
):
    del sys.modules["db"]
