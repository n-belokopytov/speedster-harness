"""CLI tests for `tools/validate_em_breakdown.py` and `tools/normalize_em_breakdown.py`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from speedster.contracts.em_breakdown import normalize_breakdown

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_CLI = REPO_ROOT / "speedster" / "cli" / "validate_em_breakdown.py"
NORMALIZE_CLI = REPO_ROOT / "speedster" / "cli" / "normalize_em_breakdown.py"


def _valid_task(tid: str, depends_on: list[str] | None = None, children: list[dict] | None = None) -> dict:
    return {
        "id": tid,
        "description": f"Implement task {tid} responsibilities.",
        "acceptance_criteria": {
            "functional": [f"{tid} produces expected outputs for happy path and error cases."],
            "solid": (
                "The implementation adheres to SOLID principles by separating schema, "
                "logic, and transport concerns."
            ),
            "yagni_kiss": (
                "The implementation adheres to YAGNI and KISS by avoiding speculative "
                "abstractions beyond the task scope."
            ),
            "testing": (
                "Well-designed unit tests cover happy path and error cases, "
                "with minimum unit test coverage of 80%+ for touched modules."
            ),
        },
        "context_files": [f"pkg/{tid}.py"],
        "context_rationale": f"{tid} only modifies this module.",
        "depends_on": depends_on or [],
        "estimated_context_tokens": 4000,
        "estimated_work_tokens": 12000,
        "complexity_level": "simple",
        "target_model_class": "mid-size-25B",
        "status": "pending",
        "qa_rounds": 0,
        "feedback": None,
        "tasks": children or [],
    }


def _write_valid_breakdown(path: Path) -> None:
    root = _valid_task(
        "root",
        children=[
            _valid_task("a"),
            _valid_task("b", depends_on=["a"]),
        ],
    )
    path.write_text(json.dumps(normalize_breakdown(root), indent=2))


@pytest.fixture
def valid_path(tmp_path: Path) -> Path:
    path = tmp_path / "valid.json"
    _write_valid_breakdown(path)
    return path


@pytest.fixture
def unsorted_children_path(tmp_path: Path) -> Path:
    path = tmp_path / "unsorted.json"
    root = _valid_task("root", children=[_valid_task("b"), _valid_task("a")])
    path.write_text(json.dumps(root, indent=2))
    return path


@pytest.fixture
def invalid_path(tmp_path: Path) -> Path:
    path = tmp_path / "invalid.json"
    root = _valid_task("root", children=[_valid_task("a", depends_on=["ghost"])])
    path.write_text(json.dumps(root, indent=2))
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
    def test_stdout_sorts_children_by_id(self, unsorted_children_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(NORMALIZE_CLI), str(unsorted_children_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert [c["id"] for c in data["tasks"]] == ["a", "b"]

    def test_in_place_rewrites_file(self, unsorted_children_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(NORMALIZE_CLI), str(unsorted_children_path), "--in-place"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(unsorted_children_path.read_text())
        assert [c["id"] for c in data["tasks"]] == ["a", "b"]

    def test_exit_two_on_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.json"
        result = subprocess.run(
            [sys.executable, str(NORMALIZE_CLI), str(missing)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "breakdown file not found" in result.stderr
