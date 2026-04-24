"""CLI tests for `tools/validate_engineer_output.py` and `tools/validate_engineer_input.py`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_OUTPUT_CLI = REPO_ROOT / "speedster" / "cli" / "validate_engineer_output.py"
VALIDATE_INPUT_CLI = REPO_ROOT / "speedster" / "cli" / "validate_engineer_input.py"


def _implemented_output(branch: str = "speedster/root", task_id: str = "leaf-1") -> dict:
    return {
        "task_id": task_id,
        "status": "implemented",
        "branch": branch,
        "files_changed": ["pkg/module.py"],
        "tests_added_or_updated": ["tests/test_module.py"],
        "acceptance_evidence": {
            "functional": [
                {
                    "criterion": "module returns expected value",
                    "evidence": "tests/test_module.py::test_happy_path",
                }
            ],
            "solid": "New port isolates I/O from the domain service.",
            "yagni_kiss": "No base class or registry was introduced.",
            "testing": "tests/test_module.py covers 92% of pkg/module.py.",
        },
        "assumptions": [],
        "notes": "",
        "blocked_reason": "",
        "requested_context": [],
    }


def _valid_input(branch: str = "speedster/root", task_id: str = "leaf-1") -> dict:
    return {
        "task": {
            "id": task_id,
            "description": "Implement the task scope.",
            "acceptance_criteria": {"functional": ["does the thing"]},
            "context_files": ["pkg/module.py"],
        },
        "repo": {"branch": branch, "root": "/workspace/repo"},
        "prior_feedback": None,
    }


@pytest.fixture
def valid_output_path(tmp_path: Path) -> Path:
    path = tmp_path / "output.json"
    path.write_text(json.dumps(_implemented_output(), indent=2))
    return path


@pytest.fixture
def invalid_output_path(tmp_path: Path) -> Path:
    path = tmp_path / "output_invalid.json"
    bad = _implemented_output()
    bad["files_changed"] = []  # violates implemented-with-files-changed structural rule
    path.write_text(json.dumps(bad, indent=2))
    return path


@pytest.fixture
def valid_input_path(tmp_path: Path) -> Path:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(_valid_input(), indent=2))
    return path


@pytest.fixture
def invalid_input_path(tmp_path: Path) -> Path:
    path = tmp_path / "input_invalid.json"
    bad = _valid_input()
    bad["repo"]["branch"] = "feature/foo"  # violates speedster/<id> pattern
    path.write_text(json.dumps(bad, indent=2))
    return path


class TestValidateOutputCLI:
    def test_exit_zero_on_valid(self, valid_output_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_OUTPUT_CLI), str(valid_output_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "VALID" in result.stdout

    def test_exit_one_on_invalid(self, invalid_output_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_OUTPUT_CLI), str(invalid_output_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "INVALID" in result.stderr

    def test_exit_two_on_missing_payload(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.json"
        result = subprocess.run(
            [sys.executable, str(VALIDATE_OUTPUT_CLI), str(missing)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "payload file not found" in result.stderr

    def test_exit_two_on_missing_schema(
        self, valid_output_path: Path, tmp_path: Path
    ) -> None:
        missing_schema = tmp_path / "missing_schema.json"
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATE_OUTPUT_CLI),
                str(valid_output_path),
                "--schema",
                str(missing_schema),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "schema file not found" in result.stderr


class TestValidateInputCLI:
    def test_exit_zero_on_valid(self, valid_input_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_INPUT_CLI), str(valid_input_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "VALID" in result.stdout

    def test_exit_one_on_invalid(self, invalid_input_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATE_INPUT_CLI), str(invalid_input_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "INVALID" in result.stderr

    def test_exit_two_on_missing_payload(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.json"
        result = subprocess.run(
            [sys.executable, str(VALIDATE_INPUT_CLI), str(missing)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "payload file not found" in result.stderr
