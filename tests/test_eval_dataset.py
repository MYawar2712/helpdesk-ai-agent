"""Unit tests verifying eval/golden_dataset.csv integrity and schema compliance."""

import csv
from pathlib import Path

GOLDEN_DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "eval" / "golden_dataset.csv"
)
RUBRIC_PATH = Path(__file__).resolve().parents[1] / "eval" / "rubric.md"


def test_golden_dataset_file_exists() -> None:
    """Verify golden_dataset.csv and rubric.md exist in eval/."""
    assert GOLDEN_DATASET_PATH.exists()
    assert RUBRIC_PATH.exists()


def test_golden_dataset_contents_valid() -> None:
    """Verify CSV header, row count, non-empty fields, and valid route values."""
    with GOLDEN_DATASET_PATH.open(mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    # Verify at least 20-30 rows
    assert len(rows) >= 20

    allowed_routes = {"tool", "rag", "handoff", "respond"}

    for index, row in enumerate(rows, 1):
        assert row["id"], f"Row {index} is missing id"
        assert row["case_type"], f"Row {index} is missing case_type"
        assert row["input_text"], f"Row {index} is missing input_text"
        assert (
            row["expected_route"] in allowed_routes
        ), f"Row {index} has invalid expected_route: {row['expected_route']}"
        val = row["requires_human_handoff"].lower()
        assert val in {"true", "false"}, f"Row {index} invalid handoff: {val}"
        if row["expected_route"] == "tool":
            assert row[
                "expected_tool"
            ], f"Row {index} expects tool route but has empty expected_tool"
