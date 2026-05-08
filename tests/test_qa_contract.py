"""Unit tests for `tools/qa_contract.py` library functions."""

from __future__ import annotations

import copy

import pytest

from speedster.contracts.qa_contract import (
    ContractValidationError,
    _validate_output_structural,
    validate_qa_output,
)


def _engineer_output(
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


def _approved_output(
    *,
    branch: str = "speedster/root",
    task_id: str = "leaf-1",
    commit: str = "abc1234",
    round_: int = 1,
) -> dict:
    return {
        "task_id": task_id,
        "status": "approved",
        "branch": branch,
        "commit": commit,
        "round": round_,
        "findings": {
            "functional": [
                {
                    "criterion": "module returns expected value for valid inputs",
                    "verdict": "met",
                    "evidence": "tests/test_module.py::test_happy_path asserts f() == 1",
                }
            ],
            "solid": {
                "verdict": "met",
                "evidence": "pkg/module.py introduces an I/O port at new seam.",
            },
            "yagni_kiss": {
                "verdict": "met",
                "evidence": "No unused helpers in diff.",
            },
            "testing": {
                "verdict": "met",
                "evidence": "tests/test_module.py covers new branch.",
            },
        },
        "rejection_reasons": [],
        "notes": "",
    }


def _rejected_output(*, reason: str = "Add a test covering the 401 branch.") -> dict:
    out = _approved_output()
    out["status"] = "rejected"
    out["findings"]["functional"][0]["verdict"] = "unmet"
    out["findings"]["functional"][0]["evidence"] = "No test added for the 401 branch."
    out["rejection_reasons"] = [reason]
    return out


def _uncertain_output() -> dict:
    out = _approved_output()
    out["status"] = "rejected"
    out["findings"]["testing"]["verdict"] = "uncertain"
    out["findings"]["testing"]["evidence"] = (
        "Cannot confirm coverage without coverage tool output."
    )
    out["rejection_reasons"] = [
        "Add a coverage report or explicit branch assertion for pkg/module.py.",
    ]
    return out


# ---------------- validate_qa_output: happy paths ----------------


class TestValidateOutputHappy:
    def test_approved_happy_path(self) -> None:
        validate_qa_output(_approved_output())

    def test_rejected_with_unmet_verdict(self) -> None:
        validate_qa_output(_rejected_output())

    def test_rejected_with_uncertain_verdict(self) -> None:
        validate_qa_output(_uncertain_output())

    def test_hyphenated_branch_ok(self) -> None:
        validate_qa_output(
            _approved_output(
                branch="speedster/iter-1-vertical-slice",
                task_id="iter-1-vertical-slice-2",
            )
        )

    def test_short_commit_sha_ok(self) -> None:
        validate_qa_output(_approved_output(commit="abcdef1"))

    def test_full_commit_sha_ok(self) -> None:
        validate_qa_output(_approved_output(commit="a" * 40))


# ---------------- validate_qa_output: failures ----------------


class TestValidateOutputFailures:
    def test_unknown_status_rejected(self) -> None:
        out = _approved_output()
        out["status"] = "passed"
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_unknown_verdict_rejected(self) -> None:
        out = _approved_output()
        out["findings"]["functional"][0]["verdict"] = "ok"
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_missing_required_field_rejected(self) -> None:
        out = _approved_output()
        del out["commit"]
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_additional_property_rejected(self) -> None:
        out = _approved_output()
        out["reviewer"] = "qa-agent-1"
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_invalid_branch_pattern_rejected(self) -> None:
        out = _approved_output()
        out["branch"] = "feature/foo"
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_invalid_commit_pattern_rejected(self) -> None:
        out = _approved_output()
        out["commit"] = "not-a-sha"
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_commit_too_short_rejected(self) -> None:
        out = _approved_output()
        out["commit"] = "abc12"  # 5 chars < 7
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_commit_too_long_rejected(self) -> None:
        out = _approved_output()
        out["commit"] = "a" * 41
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_round_zero_rejected(self) -> None:
        out = _approved_output()
        out["round"] = 0
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_functional_findings_empty_rejected(self) -> None:
        out = _approved_output()
        out["findings"]["functional"] = []
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_missing_category_finding_rejected(self) -> None:
        out = _approved_output()
        del out["findings"]["solid"]
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_approved_with_rejection_reasons_rejected(self) -> None:
        out = _approved_output()
        out["rejection_reasons"] = ["stray reason"]
        with pytest.raises(ContractValidationError, match="rejection_reasons"):
            validate_qa_output(out)

    def test_approved_with_unmet_verdict_rejected(self) -> None:
        out = _approved_output()
        out["findings"]["solid"]["verdict"] = "unmet"
        with pytest.raises(ContractValidationError, match="met"):
            validate_qa_output(out)

    def test_approved_with_uncertain_verdict_rejected(self) -> None:
        out = _approved_output()
        out["findings"]["testing"]["verdict"] = "uncertain"
        with pytest.raises(ContractValidationError, match="met"):
            validate_qa_output(out)

    def test_rejected_with_empty_reasons_rejected(self) -> None:
        out = _rejected_output()
        out["rejection_reasons"] = []
        with pytest.raises(ContractValidationError, match="rejection_reasons"):
            validate_qa_output(out)

    def test_rejected_with_all_met_verdicts_rejected(self) -> None:
        out = _approved_output()
        out["status"] = "rejected"
        out["rejection_reasons"] = ["stale"]
        with pytest.raises(ContractValidationError, match="unmet"):
            validate_qa_output(out)

    def test_notes_too_long_rejected(self) -> None:
        out = _approved_output()
        out["notes"] = "x" * 281
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_rejection_reason_too_long_rejected(self) -> None:
        out = _rejected_output()
        out["rejection_reasons"] = ["x" * 2001]
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_duplicate_rejection_reasons_rejected(self) -> None:
        out = _rejected_output()
        out["rejection_reasons"] = ["same", "same"]
        with pytest.raises(Exception):
            validate_qa_output(out)

    def test_finding_additional_property_rejected(self) -> None:
        out = _approved_output()
        out["findings"]["solid"]["confidence"] = 0.9
        with pytest.raises(Exception):
            validate_qa_output(out)


# ---------------- private structural helpers ----------------


class TestValidateOutputStructural:
    def test_does_not_mutate_input(self) -> None:
        out = _approved_output()
        original = copy.deepcopy(out)
        _validate_output_structural(out)
        assert out == original
