"""CLI tests for `tools/validate_em_breakdown.py` and `tools/normalize_em_breakdown.py`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from em_breakdown import normalize_breakdown

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_CLI = REPO_ROOT / "tools" / "validate_em_breakdown.py"
NORMALIZE_CLI = REPO_ROOT / "tools" / "normalize_em_breakdown.py"


def _valid_subtask(sid: str, depends_on: list[str] | None = None) -> dict:
    return {
        "id": sid,
        "description": f"Implement subtask {sid} responsibilities.",
        "acceptance_criteria": {
            "functional": [f"{sid} produces expected outputs for happy path and error cases."],
            "solid": (
                "The implementation adheres to SOLID principles by separating schema, "
                "logic, and transport concerns."
            ),
            "yagni_kiss": (
                "The implementation adheres to YAGNI and KISS by avoiding speculative "
                "abstractions beyond the subtask scope."
            ),
            "testing": (
                "Well-designed unit tests cover happy path and error cases, "
                "with minimum unit test coverage of 80%+ for touched modules."
            ),
        },
        "context_files": [f"pkg/{sid}.py"],
        "context_rationale": f"{sid} only modifies this module.",
        "depends_on": depends_on or [],
        "parallel_group": 0,
        "estimated_context_tokens": 4000,
        "estimated_work_tokens": 12000,
        "complexity_level": "simple",
        "target_model_class": "mid-size-25B",
        "status": "pending",
        "qa_rounds": 0,
        "feedback": None,
    }


def _write_valid_breakdown(path: Path) -> None:
    subs = [
        _valid_subtask("t-1"),
        _valid_subtask("t-2", depends_on=["t-1"]),
    ]
    path.write_text(json.dumps(normalize_breakdown({"task_id": "t", "subtasks": subs}), indent=2))


@pytest.fixture
def valid_path(tmp_path: Path) -> Path:
    path = tmp_path / "valid.json"
    _write_valid_breakdown(path)
    return path


@pytest.fixture
def invalid_path(tmp_path: Path) -> Path:
    path = tmp_path / "invalid.json"
    subs = [
        _valid_subtask("t-2", depends_on=["t-1"]),
        _valid_subtask("t-1"),
    ]
    path.write_text(json.dumps({"task_id": "t", "subtasks": subs}, indent=2))
    return path


class TestValidateCLI:
    def test_exit_zero_on_valid(self, valid_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_CLI), str(valid_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "VALID" in result.stdout

    def test_exit_one_on_invalid(self, invalid_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_CLI), str(invalid_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "INVALID" in result.stderr

    def test_exit_two_on_missing_breakdown(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.json"
        result = subprocess.run(
            [sys.executable, str(VALIDATE_CLI), str(missing)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "breakdown file not found" in result.stderr

    def test_exit_two_on_missing_schema(self, valid_path: Path, tmp_path: Path) -> None:
        missing_schema = tmp_path / "missing_schema.json"
        result = subprocess.run(
            [sys.executable, str(VALIDATE_CLI), str(valid_path), "--schema", str(missing_schema)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "schema file not found" in result.stderr


class TestNormalizeCLI:
    def test_stdout_output_is_sorted(self, invalid_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(NORMALIZE_CLI), str(invalid_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        ids = [s["id"] for s in data["subtasks"]]
        assert ids == ["t-1", "t-2"]

    def test_in_place_rewrites_file(self, invalid_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(NORMALIZE_CLI), str(invalid_path), "--in-place"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(invalid_path.read_text())
        ids = [s["id"] for s in data["subtasks"]]
        assert ids == ["t-1", "t-2"]

    def test_exit_two_on_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.json"
        result = subprocess.run(
            [sys.executable, str(NORMALIZE_CLI), str(missing)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "breakdown file not found" in result.stderr
