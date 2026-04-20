"""Unit tests for `tools/em_breakdown.py` library functions."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from em_breakdown import (
    BreakdownValidationError,
    _validate_graph,
    _validate_structural,
    compute_parallel_groups,
    load_breakdown,
    normalize_breakdown,
    validate_breakdown,
)


def _subtask(
    sid: str,
    depends_on: list[str] | None = None,
    parallel_group: int = 0,
    context_files: list[str] | None = None,
) -> dict:
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
        "context_files": context_files or [f"pkg/{sid}.py"],
        "context_rationale": f"{sid} only modifies this module.",
        "depends_on": depends_on or [],
        "parallel_group": parallel_group,
        "estimated_context_tokens": 4000,
        "estimated_work_tokens": 12000,
        "complexity_level": "simple",
        "target_model_class": "mid-size-25B",
        "status": "pending",
        "qa_rounds": 0,
        "feedback": None,
    }


def _breakdown(subs: list[dict], task_id: str = "t") -> dict:
    return {"task_id": task_id, "subtasks": subs}


# ---------------- compute_parallel_groups ----------------


class TestComputeParallelGroups:
    def test_no_dependencies_yields_group_zero(self) -> None:
        subs = [_subtask("t-1"), _subtask("t-2")]
        assert compute_parallel_groups(subs) == {"t-1": 0, "t-2": 0}

    def test_linear_chain_increments_groups(self) -> None:
        subs = [
            _subtask("t-1"),
            _subtask("t-2", depends_on=["t-1"]),
            _subtask("t-3", depends_on=["t-2"]),
        ]
        assert compute_parallel_groups(subs) == {"t-1": 0, "t-2": 1, "t-3": 2}

    def test_diamond_picks_max_dependency_group(self) -> None:
        subs = [
            _subtask("t-1"),
            _subtask("t-2", depends_on=["t-1"]),
            _subtask("t-3", depends_on=["t-1"]),
            _subtask("t-4", depends_on=["t-2", "t-3"]),
        ]
        assert compute_parallel_groups(subs) == {"t-1": 0, "t-2": 1, "t-3": 1, "t-4": 2}

    def test_cycle_raises(self) -> None:
        subs = [
            _subtask("t-1", depends_on=["t-2"]),
            _subtask("t-2", depends_on=["t-1"]),
        ]
        with pytest.raises(BreakdownValidationError, match="Cyclic dependency"):
            compute_parallel_groups(subs)

    def test_duplicate_id_raises(self) -> None:
        subs = [_subtask("t-1"), _subtask("t-1")]
        with pytest.raises(BreakdownValidationError, match="Duplicate subtask id"):
            compute_parallel_groups(subs)

    def test_missing_id_raises(self) -> None:
        bad = _subtask("t-1")
        del bad["id"]
        with pytest.raises(BreakdownValidationError, match="non-empty string `id`"):
            compute_parallel_groups([bad])

    def test_empty_id_raises(self) -> None:
        bad = _subtask("t-1")
        bad["id"] = ""
        with pytest.raises(BreakdownValidationError, match="non-empty string `id`"):
            compute_parallel_groups([bad])

    def test_unknown_dependency_raises(self) -> None:
        subs = [_subtask("t-1", depends_on=["t-missing"])]
        with pytest.raises(BreakdownValidationError, match="unknown subtask `t-missing`"):
            compute_parallel_groups(subs)


# ---------------- normalize_breakdown ----------------


class TestNormalizeBreakdown:
    def test_renumbers_and_sorts_by_group_then_id(self) -> None:
        # Provided IDs are deliberately out of final order
        subs = [
            _subtask("x-2", depends_on=["x-1"]),
            _subtask("x-1"),
        ]
        out = normalize_breakdown(_breakdown(subs, task_id="x"))
        ids = [s["id"] for s in out["subtasks"]]
        assert ids == ["x-1", "x-2"]
        assert out["subtasks"][0]["parallel_group"] == 0
        assert out["subtasks"][1]["parallel_group"] == 1
        assert out["subtasks"][1]["depends_on"] == ["x-1"]

    def test_dedupes_and_sorts_lists(self) -> None:
        s = _subtask(
            "t-1",
            context_files=["b.py", "a.py", "b.py"],
        )
        s["depends_on"] = []
        out = normalize_breakdown(_breakdown([s]))
        assert out["subtasks"][0]["context_files"] == ["a.py", "b.py"]

    def test_recomputes_parallel_group_even_if_input_wrong(self) -> None:
        subs = [
            _subtask("t-1", parallel_group=9),
            _subtask("t-2", depends_on=["t-1"], parallel_group=9),
        ]
        out = normalize_breakdown(_breakdown(subs))
        assert [s["parallel_group"] for s in out["subtasks"]] == [0, 1]

    def test_empty_subtasks_raises(self) -> None:
        with pytest.raises(BreakdownValidationError, match="non-empty list"):
            normalize_breakdown({"task_id": "t", "subtasks": []})

    def test_missing_task_id_raises(self) -> None:
        with pytest.raises(BreakdownValidationError, match="task_id"):
            normalize_breakdown({"subtasks": [_subtask("t-1")]})

    def test_does_not_mutate_input(self) -> None:
        subs = [_subtask("t-1"), _subtask("t-2", depends_on=["t-1"], parallel_group=5)]
        original = copy.deepcopy(subs)
        _ = normalize_breakdown(_breakdown(subs))
        assert subs == original


# ---------------- validate_breakdown ----------------


class TestValidateBreakdown:
    def _valid(self) -> dict:
        subs = [
            _subtask("t-1"),
            _subtask("t-2", depends_on=["t-1"]),
        ]
        return normalize_breakdown(_breakdown(subs))

    def test_happy_path(self) -> None:
        validate_breakdown(self._valid())

    def test_unsorted_output_fails(self) -> None:
        b = self._valid()
        b["subtasks"].reverse()
        with pytest.raises(BreakdownValidationError, match="sorted"):
            validate_breakdown(b)

    def test_parallel_group_drift_fails(self) -> None:
        b = self._valid()
        b["subtasks"][1]["parallel_group"] = 5
        with pytest.raises(BreakdownValidationError, match="parallel_group"):
            validate_breakdown(b)

    def test_invalid_solid_prefix_fails(self) -> None:
        b = self._valid()
        b["subtasks"][0]["acceptance_criteria"]["solid"] = "S is good."
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_missing_testing_coverage_phrase_fails(self) -> None:
        b = self._valid()
        b["subtasks"][0]["acceptance_criteria"]["testing"] = (
            "Well-designed unit tests cover the behavior."
        )
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_too_many_functional_items_fails(self) -> None:
        b = self._valid()
        b["subtasks"][0]["acceptance_criteria"]["functional"] = [
            f"check {i} passes assertion" for i in range(6)
        ]
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_duplicate_context_files_fails(self) -> None:
        b = self._valid()
        b["subtasks"][0]["context_files"] = ["a.py", "a.py"]
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_self_dependency_fails(self) -> None:
        b = self._valid()
        b["subtasks"][0]["depends_on"] = ["t-1"]
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_unknown_dependency_fails(self) -> None:
        b = self._valid()
        b["subtasks"][1]["depends_on"] = ["t-missing"]
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_wrong_target_model_class_fails(self) -> None:
        b = self._valid()
        b["subtasks"][0]["target_model_class"] = "other"
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_token_limits_enforced(self) -> None:
        b = self._valid()
        b["subtasks"][0]["estimated_context_tokens"] = 20000
        with pytest.raises(Exception):
            validate_breakdown(b)


# ---------------- private structural / graph checks ----------------


class TestValidateStructural:
    """Directly exercise structural branches that JSON Schema catches first."""

    def _base(self) -> dict:
        subs = [_subtask("t-1"), _subtask("t-2", depends_on=["t-1"])]
        return normalize_breakdown(_breakdown(subs))

    def test_invalid_solid_prefix(self) -> None:
        b = self._base()
        b["subtasks"][0]["acceptance_criteria"]["solid"] = "Solid stuff."
        with pytest.raises(BreakdownValidationError, match="solid.*prefix invalid"):
            _validate_structural(b)

    def test_invalid_yagni_kiss_prefix(self) -> None:
        b = self._base()
        b["subtasks"][0]["acceptance_criteria"]["yagni_kiss"] = "Minimal design."
        with pytest.raises(BreakdownValidationError, match="yagni_kiss.*prefix invalid"):
            _validate_structural(b)

    def test_invalid_testing_prefix(self) -> None:
        b = self._base()
        b["subtasks"][0]["acceptance_criteria"]["testing"] = "Tests exist."
        with pytest.raises(BreakdownValidationError, match="testing.*prefix invalid"):
            _validate_structural(b)

    def test_missing_coverage_phrase(self) -> None:
        b = self._base()
        b["subtasks"][0]["acceptance_criteria"]["testing"] = (
            "Well-designed unit tests cover the change end to end."
        )
        with pytest.raises(BreakdownValidationError, match="missing required coverage phrase"):
            _validate_structural(b)

    def test_duplicate_context_files(self) -> None:
        b = self._base()
        b["subtasks"][0]["context_files"] = ["a.py", "a.py"]
        with pytest.raises(BreakdownValidationError, match="Duplicate `context_files`"):
            _validate_structural(b)

    def test_self_dependency(self) -> None:
        b = self._base()
        b["subtasks"][0]["depends_on"] = ["t-1"]
        with pytest.raises(BreakdownValidationError, match="Self-dependency"):
            _validate_structural(b)


class TestValidateGraph:
    def _base(self) -> dict:
        subs = [_subtask("t-1"), _subtask("t-2", depends_on=["t-1"])]
        return normalize_breakdown(_breakdown(subs))

    def test_unknown_dependency(self) -> None:
        b = self._base()
        b["subtasks"][1]["depends_on"] = ["t-99"]
        with pytest.raises(BreakdownValidationError, match="unknown subtask `t-99`"):
            _validate_graph(b)

    def test_cycle_detected(self) -> None:
        # Build a cycle that passes schema pattern checks for IDs
        s1 = _subtask("t-1", depends_on=["t-2"], parallel_group=0)
        s2 = _subtask("t-2", depends_on=["t-1"], parallel_group=0)
        b = _breakdown([s1, s2])
        with pytest.raises(BreakdownValidationError, match="Cyclic"):
            _validate_graph(b)

    def test_group_ordering_violation_via_drift(self) -> None:
        """`parallel_group` drift check fires before ordering check."""
        b = self._base()
        b["subtasks"][1]["parallel_group"] = 0
        with pytest.raises(BreakdownValidationError, match="parallel_group.*drift"):
            _validate_graph(b)


# ---------------- load_breakdown ----------------


class TestLoadBreakdown:
    def test_loads_object(self, tmp_path: Path) -> None:
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"task_id": "t", "subtasks": []}))
        assert load_breakdown(path) == {"task_id": "t", "subtasks": []}

    def test_non_object_top_level_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps([1, 2]))
        with pytest.raises(BreakdownValidationError, match="Top-level JSON"):
            load_breakdown(path)
