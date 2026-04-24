"""Unit tests for the output validator."""

from __future__ import annotations

import json

import pytest

from speedster.output_validator import OutputValidator, ValidationError


@pytest.fixture
def validator() -> OutputValidator:
    """Create an output validator instance."""

    return OutputValidator()


def make_valid_breakdown() -> dict:
    """Create a valid EM breakdown that passes schema validation."""

    return {
        "id": "task-001",
        "description": "Add user authentication with JWT",
        "acceptance_criteria": {
            "functional": ["Login endpoint returns 200 on valid credentials"],
            "solid": "The implementation adheres to SOLID principles by separating concerns.",
            "yagni_kiss": "The implementation adheres to YAGNI and KISS by keeping it simple.",
            "testing": "Well-designed unit tests cover the behavior, with minimum unit test coverage of 80%+ for touched modules.",
        },
        "context_files": ["src/auth.py"],
        "context_rationale": "Auth module needs changes",
        "depends_on": [],
        "estimated_context_tokens": 1000,
        "estimated_work_tokens": 5000,
        "complexity_level": "simple",
        "target_model_class": "mid-size-25B",
        "status": "pending",
        "qa_rounds": 0,
        "feedback": None,
        "tasks": [],
    }


def make_valid_engineer_output(status: str = "implemented") -> dict:
    """Create a valid engineer output that passes schema validation."""

    output = {
        "task_id": "task-001",
        "status": status,
        "branch": "speedster/task-001",
        "files_changed": ["src/auth.py"],
        "tests_added_or_updated": ["tests/test_auth.py"],
        "acceptance_evidence": {
            "functional": [
                {
                    "criterion": "Login returns 200",
                    "evidence": "Test passes with valid credentials",
                }
            ],
            "solid": "Separation of concerns maintained",
            "yagni_kiss": "Simple solution implemented",
            "testing": "Unit tests added for auth module",
        },
        "assumptions": [],
        "notes": "",
        "blocked_reason": "",
        "requested_context": [],
    }

    if status == "blocked":
        output["blocked_reason"] = "External dependency not available"
        output["files_changed"] = []
        output["tests_added_or_updated"] = []
    elif status == "needs_context":
        output["requested_context"] = ["path/to/missing/file.py"]
        output["files_changed"] = []
        output["tests_added_or_updated"] = []

    return output


def make_valid_qa_output(status: str = "approved", round_num: int = 1) -> dict:
    """Create a valid QA output that passes schema validation."""

    if status == "approved":
        return {
            "task_id": "task-001",
            "status": "approved",
            "branch": "speedster/task-001",
            "commit": "abc123def456",
            "round": round_num,
            "findings": {
                "functional": [
                    {
                        "criterion": "Login returns 200",
                        "verdict": "met",
                        "evidence": "Test passes with valid credentials",
                    }
                ],
                "solid": {
                    "verdict": "met",
                    "evidence": "Good separation of concerns",
                },
                "yagni_kiss": {
                    "verdict": "met",
                    "evidence": "Simple solution",
                },
                "testing": {
                    "verdict": "met",
                    "evidence": "Unit tests added with good coverage",
                },
            },
            "rejection_reasons": [],
            "notes": "",
        }
    else:
        return {
            "task_id": "task-001",
            "status": "rejected",
            "branch": "speedster/task-001",
            "commit": "abc123def456",
            "round": round_num,
            "findings": {
                "functional": [
                    {
                        "criterion": "Login returns 200",
                        "verdict": "unmet",
                        "evidence": "Missing error handling",
                    }
                ],
                "solid": {
                    "verdict": "met",
                    "evidence": "Good separation of concerns",
                },
                "yagni_kiss": {
                    "verdict": "met",
                    "evidence": "Simple solution",
                },
                "testing": {
                    "verdict": "met",
                    "evidence": "Unit tests added with good coverage",
                },
            },
            "rejection_reasons": ["Missing error handling"],
            "notes": "",
        }


class TestValidateEMBreakdown:
    def test_valid_breakdown(self, validator: OutputValidator) -> None:
        breakdown = make_valid_breakdown()
        result = validator.validate_em_breakdown(breakdown)
        assert result == breakdown

    def test_valid_breakdown_string(self, validator: OutputValidator) -> None:
        breakdown = make_valid_breakdown()
        result = validator.validate_em_breakdown(json.dumps(breakdown))
        assert result == breakdown

    def test_invalid_json(self, validator: OutputValidator) -> None:
        result = validator.validate("not json", "em_breakdown")
        assert result is None

    def test_missing_required_field(self, validator: OutputValidator) -> None:
        breakdown = make_valid_breakdown()
        del breakdown["description"]

        with pytest.raises(ValidationError):
            validator.validate_em_breakdown(breakdown)


class TestValidateEngineerOutput:
    def test_valid_implemented(self, validator: OutputValidator) -> None:
        output = make_valid_engineer_output("implemented")
        result = validator.validate_engineer_output(output)
        assert result == output

    def test_valid_blocked(self, validator: OutputValidator) -> None:
        output = make_valid_engineer_output("blocked")
        result = validator.validate_engineer_output(output)
        assert result == output

    def test_valid_needs_context(self, validator: OutputValidator) -> None:
        output = make_valid_engineer_output("needs_context")
        result = validator.validate_engineer_output(output)
        assert result == output

    def test_implemented_no_files(self, validator: OutputValidator) -> None:
        output = make_valid_engineer_output("implemented")
        output["files_changed"] = []

        with pytest.raises(ValidationError, match="files_changed"):
            validator.validate_engineer_output(output)


class TestValidateQAOutput:
    def test_valid_approved(self, validator: OutputValidator) -> None:
        output = make_valid_qa_output("approved")
        result = validator.validate_qa_output(output)
        assert result == output

    def test_valid_rejected(self, validator: OutputValidator) -> None:
        output = make_valid_qa_output("rejected")
        result = validator.validate_qa_output(output)
        assert result == output

    def test_approved_with_rejection_reasons(self, validator: OutputValidator) -> None:
        output = make_valid_qa_output("approved")
        output["rejection_reasons"] = ["Should be empty"]

        with pytest.raises(ValidationError, match="rejection_reasons"):
            validator.validate_qa_output(output)


class TestValidateUnknownType:
    def test_unknown_output_type(self, validator: OutputValidator) -> None:
        with pytest.raises(ValidationError, match="Unknown output type"):
            validator.validate({"key": "value"}, "unknown_type")
