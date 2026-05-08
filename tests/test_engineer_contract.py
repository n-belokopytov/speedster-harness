"""Unit tests for `tools/engineer_contract.py` library functions."""

from __future__ import annotations

import copy

import pytest

from speedster.contracts.engineer_contract import (
    ContractValidationError,
    _validate_output_structural,
    validate_engineer_output,
)


def _implemented_output(
    *,
    branch: str = "speedster/root",
    task_id: str = "leaf-1",
) -> dict:
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


def _blocked_output() -> dict:
    out = _implemented_output()
    out["status"] = "blocked"
    out["files_changed"] = []
    out["tests_added_or_updated"] = []
    out["blocked_reason"] = "Criterion `x` requires a module outside context_files."
    return out


def _needs_context_output() -> dict:
    out = _implemented_output()
    out["status"] = "needs_context"
    out["files_changed"] = []
    out["tests_added_or_updated"] = []
    out["requested_context"] = ["pkg/dep.py"]
    return out


# ---------------- validate_engineer_output: happy paths ----------------


class TestValidateOutputHappy:
    def test_implemented_happy_path(self) -> None:
        validate_engineer_output(_implemented_output())

    def test_blocked_happy_path(self) -> None:
        validate_engineer_output(_blocked_output())

    def test_needs_context_happy_path(self) -> None:
        validate_engineer_output(_needs_context_output())

    def test_hyphenated_branch_ok(self) -> None:
        validate_engineer_output(
            _implemented_output(
                branch="speedster/iter-1-vertical-slice",
                task_id="iter-1-vertical-slice-2",
            )
        )

    def test_task_id_independent_of_branch(self) -> None:
        """Tree task ids are unrelated to the branch name string."""
        validate_engineer_output(
            _implemented_output(branch="speedster/root", task_id="unrelated.leaf")
        )


# ---------------- validate_engineer_output: failures ----------------


class TestValidateOutputFailures:
    def test_unknown_status_rejected(self) -> None:
        out = _implemented_output()
        out["status"] = "completed"
        with pytest.raises(Exception):
            validate_engineer_output(out)

    def test_missing_required_field_rejected(self) -> None:
        out = _implemented_output()
        del out["branch"]
        with pytest.raises(Exception):
            validate_engineer_output(out)

    def test_additional_property_rejected(self) -> None:
        out = _implemented_output()
        out["commit_sha"] = "a" * 40
        with pytest.raises(Exception):
            validate_engineer_output(out)

    def test_legacy_subtask_id_rejected(self) -> None:
        out = _implemented_output()
        out["subtask_id"] = out.pop("task_id")
        with pytest.raises(Exception):
            validate_engineer_output(out)

    def test_invalid_branch_pattern_rejected(self) -> None:
        out = _implemented_output()
        out["branch"] = "feature/foo"
        with pytest.raises(Exception):
            validate_engineer_output(out)

    def test_colon_in_branch_rejected(self) -> None:
        out = _implemented_output()
        out["branch"] = "speedster/task:1"
        with pytest.raises(Exception):
            validate_engineer_output(out)

    def test_implemented_without_files_changed_rejected(self) -> None:
        out = _implemented_output()
        out["files_changed"] = []
        with pytest.raises(ContractValidationError, match="files_changed"):
            validate_engineer_output(out)

    def test_implemented_with_blocked_reason_rejected(self) -> None:
        out = _implemented_output()
        out["blocked_reason"] = "stray text"
        with pytest.raises(ContractValidationError, match="blocked_reason"):
            validate_engineer_output(out)

    def test_implemented_with_requested_context_rejected(self) -> None:
        out = _implemented_output()
        out["requested_context"] = ["pkg/x.py"]
        with pytest.raises(ContractValidationError, match="requested_context"):
            validate_engineer_output(out)

    def test_blocked_without_reason_rejected(self) -> None:
        out = _blocked_output()
        out["blocked_reason"] = ""
        with pytest.raises(ContractValidationError, match="blocked_reason"):
            validate_engineer_output(out)

    def test_needs_context_without_requests_rejected(self) -> None:
        out = _needs_context_output()
        out["requested_context"] = []
        with pytest.raises(ContractValidationError, match="requested_context"):
            validate_engineer_output(out)

    def test_needs_context_with_files_changed_rejected(self) -> None:
        out = _needs_context_output()
        out["files_changed"] = ["pkg/x.py"]
        with pytest.raises(ContractValidationError, match="files_changed"):
            validate_engineer_output(out)

    def test_notes_too_long_rejected(self) -> None:
        out = _implemented_output()
        out["notes"] = "x" * 281
        with pytest.raises(Exception):
            validate_engineer_output(out)

    def test_duplicate_files_changed_rejected(self) -> None:
        out = _implemented_output()
        out["files_changed"] = ["a.py", "a.py"]
        with pytest.raises(Exception):
            validate_engineer_output(out)


# ---------------- private structural helpers ----------------


class TestValidateOutputStructural:
    def test_does_not_mutate_input(self) -> None:
        out = _implemented_output()
        original = copy.deepcopy(out)
        _validate_output_structural(out)
        assert out == original
