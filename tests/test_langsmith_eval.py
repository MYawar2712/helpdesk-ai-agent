"""Unit tests for Day 23 — LangSmith tracing helpers and evaluation runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure src/ is on path for imports
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))


# ---------------------------------------------------------------------------
# Tracing helpers tests
# ---------------------------------------------------------------------------


class TestConfigureTracing:
    def test_tracing_disabled_when_no_env(self):
        from agent import tracing as tracing_mod

        def fake_getenv(key: str, default: str = "") -> str:
            # Simulate no LangSmith env vars set
            return {"LANGCHAIN_TRACING_V2": "false"}.get(key, default)

        with patch.object(tracing_mod.os, "getenv", side_effect=fake_getenv):
            result = tracing_mod.configure_tracing()
        assert result is False

    def test_tracing_enabled_returns_true(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        monkeypatch.setenv("LANGCHAIN_API_KEY", "ls-test-key-abc123")
        monkeypatch.setenv("LANGCHAIN_PROJECT", "test-project")
        from agent.tracing import configure_tracing

        result = configure_tracing()
        assert result is True

    def test_tracing_enabled_but_no_key_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
        monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
        monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
        from agent.tracing import configure_tracing

        result = configure_tracing()
        assert result is False

    def test_tracing_enabled_via_langsmith_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
        monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
        monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-key")
        monkeypatch.setenv("LANGSMITH_PROJECT", "from-langsmith")
        from agent.tracing import configure_tracing, tracing_project

        assert configure_tracing() is True
        assert tracing_project() == "from-langsmith"


class TestWrapAgentRun:
    def test_wrap_agent_run_calls_invoke(self):
        from agent.tracing import wrap_agent_run

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"route": "respond", "final_response": "Hi!"}

        result = wrap_agent_run(mock_agent, "Hello")
        mock_agent.invoke.assert_called_once_with("Hello")
        assert result["route"] == "respond"

    def test_wrap_agent_run_passes_metadata(self):
        from agent.tracing import wrap_agent_run

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"route": "tool", "final_response": "data"}

        metadata = {"case_id": "1", "case_type": "job_lookup"}
        result = wrap_agent_run(mock_agent, "job query", metadata=metadata)
        assert result["route"] == "tool"

    def test_attach_run_metadata_is_safe_without_active_run(self):
        from agent.tracing import attach_run_metadata

        attach_run_metadata(None)
        attach_run_metadata({"case_id": "1"})


# ---------------------------------------------------------------------------
# Evaluation runner tests
# ---------------------------------------------------------------------------

EVAL_SRC = Path(__file__).resolve().parents[1] / "eval" / "run_langsmith_eval.py"


def _make_minimal_state(
    route: str = "respond", response: str = "I'm happy to help"
) -> dict[str, Any]:
    return {"route": route, "final_response": response}


class TestScoreCorrectness:
    def _import(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_langsmith_eval", EVAL_SRC)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_full_pass_when_route_and_keyword_match(self):
        mod = self._import()
        row = {"expected_route": "respond", "expected_output_contains": "happy"}
        state = _make_minimal_state("respond", "I'm happy to help")
        score = mod._score_correctness(row, state)
        assert score == 5.0

    def test_partial_when_route_matches_keyword_missing(self):
        mod = self._import()
        row = {"expected_route": "respond", "expected_output_contains": "invoice"}
        state = _make_minimal_state("respond", "I'm happy to help")
        score = mod._score_correctness(row, state)
        assert score == 3.0

    def test_fail_when_route_mismatch(self):
        mod = self._import()
        row = {"expected_route": "tool", "expected_output_contains": "job-1"}
        state = _make_minimal_state("rag", "Some unrelated answer")
        score = mod._score_correctness(row, state)
        assert score == 1.0

    def test_no_keyword_required_gives_full_pass_on_correct_route(self):
        mod = self._import()
        row = {"expected_route": "handoff", "expected_output_contains": ""}
        state = _make_minimal_state("handoff", "Handing off to human support")
        score = mod._score_correctness(row, state)
        assert score == 5.0

    def test_partial_when_expected_tool_mismatches(self):
        mod = self._import()
        row = {
            "expected_route": "tool",
            "expected_tool": "get_job",
            "expected_output_contains": "job-1",
        }
        state = {
            "route": "tool",
            "tool_name": "get_customer",
            "final_response": "job-1 details",
        }
        assert mod._score_correctness(row, state) == 3.0


class TestScoreFaithfulness:
    def _import(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_langsmith_eval", EVAL_SRC)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_tool_route_with_result_returns_5(self):
        mod = self._import()
        row = {"expected_route": "tool"}
        score = mod._score_faithfulness(
            row, {"route": "tool", "tool_result": {"job": {"id": "job-1"}}}
        )
        assert score == 5.0

    def test_tool_route_missing_result_returns_1(self):
        mod = self._import()
        row = {"expected_route": "tool"}
        score = mod._score_faithfulness(row, {"route": "tool"})
        assert score == 1.0

    def test_rag_grounded_returns_5(self):
        mod = self._import()
        row = {"expected_route": "rag"}
        rag_result = MagicMock(is_grounded=True, is_fallback=False)
        score = mod._score_faithfulness(row, {"rag_result": rag_result})
        assert score == 5.0

    def test_rag_not_grounded_returns_4(self):
        mod = self._import()
        row = {"expected_route": "rag"}
        # Chunks retrieved but grounding unconfirmed -> 4.0 (soft grounding)
        rag_result = MagicMock(is_grounded=False, is_fallback=False)
        score = mod._score_faithfulness(row, {"rag_result": rag_result})
        assert score == 4.0

    def test_rag_hard_fallback_returns_1(self):
        mod = self._import()
        row = {"expected_route": "rag"}
        # Hard fallback: no chunks retrieved at all -> 1.0
        rag_result = MagicMock(is_grounded=False, is_fallback=True)
        score = mod._score_faithfulness(row, {"rag_result": rag_result})
        assert score == 1.0

    def test_rag_no_result_returns_1(self):
        mod = self._import()
        row = {"expected_route": "rag"}
        score = mod._score_faithfulness(row, {"rag_result": None})
        assert score == 1.0


class TestScoreTone:
    def _import(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_langsmith_eval", EVAL_SRC)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_polite_response_scores_5(self):
        mod = self._import()
        state = {"final_response": "I'm happy to assist you. Please let me know."}
        assert mod._score_tone(state) == 5.0

    def test_rude_response_scores_1(self):
        mod = self._import()
        state = {"final_response": "That's a stupid question."}
        assert mod._score_tone(state) == 1.0

    def test_empty_response_scores_1(self):
        mod = self._import()
        assert mod._score_tone({"final_response": ""}) == 1.0


class TestLoadDataset:
    def _import(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_langsmith_eval", EVAL_SRC)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_loads_real_dataset(self):
        mod = self._import()
        real_path = Path(__file__).resolve().parents[1] / "eval" / "golden_dataset.csv"
        rows = mod.load_dataset(real_path)
        assert len(rows) == 25
        for row in rows:
            assert row.get("input_text", "").strip() != ""
            assert row.get("expected_route") in {"tool", "rag", "handoff", "respond"}

    def test_raises_on_missing_file(self, tmp_path: Path):
        mod = self._import()
        with pytest.raises(FileNotFoundError):
            mod.load_dataset(tmp_path / "nonexistent.csv")

    def test_raises_on_empty_file(self, tmp_path: Path):
        mod = self._import()
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text(
            "id,case_type,input_text,expected_route,expected_output_contains,requires_human_handoff\n"
        )
        with pytest.raises(ValueError, match="empty"):
            mod.load_dataset(csv_path)


class TestScoreResponseAndWriteResults:
    def _import(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_langsmith_eval", EVAL_SRC)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_composite_pass_threshold(self):
        mod = self._import()
        row = {
            "expected_route": "respond",
            "expected_output_contains": "help",
            "expected_tool": "",
        }
        state = {
            "route": "respond",
            "final_response": "I'm happy to help. Please let me know.",
        }
        scores = mod.score_response(row, state)
        assert scores["correctness"] == 5.0
        assert scores["faithfulness"] == 5.0
        assert scores["tone"] == 5.0
        assert scores["composite"] == 5.0
        assert scores["passed"] is True

    def test_route_mismatch_fails(self):
        mod = self._import()
        row = {
            "expected_route": "tool",
            "expected_output_contains": "job-1",
            "expected_tool": "get_job",
        }
        state = {"route": "respond", "final_response": "hello"}
        scores = mod.score_response(row, state)
        assert scores["passed"] is False

    def test_write_results_records_failed_cases(self, tmp_path: Path):
        mod = self._import()
        results = [
            {
                "id": "1",
                "passed": True,
                "composite": 5.0,
                "case_type": "ok",
            },
            {
                "id": "2",
                "passed": False,
                "composite": 2.4,
                "case_type": "fail",
                "expected_route": "tool",
                "actual_route": "rag",
            },
        ]
        path = tmp_path / "results.json"
        written = mod.write_results(results, path)
        payload = json.loads(written.read_text(encoding="utf-8"))
        assert payload["total"] == 2
        assert payload["passed"] == 1
        assert payload["failed"] == 1
        assert payload["failed_cases"][0]["id"] == "2"
