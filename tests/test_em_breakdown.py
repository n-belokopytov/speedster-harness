"""Unit tests for `tools/em_breakdown.py` library functions (recursive tree)."""

from __future__ import annotations

import json

import pytest

from speedster.contracts.em_breakdown import (
    BreakdownValidationError,
    _build_relationships,
    _iter_tasks,
    _validate_graph,
    _validate_structural,
    validate_breakdown,
)


def _normalize(breakdown: dict) -> dict:
    """Normalize a breakdown tree: sort children by id, dedup lists."""
    out = json.loads(json.dumps(breakdown))

    def _norm(node: dict) -> None:
        node["depends_on"] = sorted(dict.fromkeys(node.get("depends_on", []) or []))
        node["context_files"] = sorted(dict.fromkeys(node.get("context_files", []) or []))
        children = node.get("tasks") or []
        for child in children:
            _norm(child)
        children.sort(key=lambda c: c["id"])
        node["tasks"] = children

    _norm(out)
    return out


def _task(
    tid: str,
    depends_on: list[str] | None = None,
    context_files: list[str] | None = None,
    children: list[dict] | None = None,
) -> dict:
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
        "context_files": context_files or [f"pkg/{tid}.py"],
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


# ---------------- _iter_tasks ----------------


class TestIterTasks:
    def test_single_node(self) -> None:
        root = _task("a")
        assert [t["id"] for t in _iter_tasks(root)] == ["a"]

    def test_preorder_root_first(self) -> None:
        root = _task("a", children=[_task("b"), _task("c", children=[_task("c-1")])])
        assert [t["id"] for t in _iter_tasks(root)] == ["a", "b", "c", "c-1"]


# ---------------- validate_breakdown ----------------


class TestValidateBreakdown:
    def _valid(self) -> dict:
        return _normalize(
            _task(
                "root",
                children=[
                    _task("a"),
                    _task("b", depends_on=["a"]),
                ],
            )
        )

    def test_happy_path_flat(self) -> None:
        validate_breakdown(self._valid())

    def test_happy_path_nested(self) -> None:
        root = _task(
            "root",
            children=[
                _task("mid", children=[_task("leaf-1"), _task("leaf-2", depends_on=["leaf-1"])]),
            ],
        )
        validate_breakdown(_normalize(root))

    def test_cross_subtree_dependency_allowed(self) -> None:
        """`depends_on` is global; two leaves in different subtrees can depend on each other."""
        root = _task(
            "root",
            children=[
                _task("sub-a", children=[_task("a-leaf")]),
                _task("sub-b", children=[_task("b-leaf", depends_on=["a-leaf"])]),
            ],
        )
        validate_breakdown(_normalize(root))

    def test_duplicate_id_fails(self) -> None:
        root = _task("root", children=[_task("dup"), _task("dup")])
        with pytest.raises(BreakdownValidationError, match="Duplicate task ids"):
            validate_breakdown(_normalize(root))

    def test_duplicate_id_across_levels_fails(self) -> None:
        root = _task("root", children=[_task("root")])
        with pytest.raises(BreakdownValidationError, match="Duplicate task ids"):
            validate_breakdown(_normalize(root))

    def test_self_dependency_fails(self) -> None:
        root = _task("root", children=[_task("a", depends_on=["a"])])
        with pytest.raises(Exception):
            validate_breakdown(_normalize(root))

    def test_unknown_dependency_fails(self) -> None:
        root = _task("root", children=[_task("a", depends_on=["ghost"])])
        with pytest.raises(BreakdownValidationError, match="unknown task"):
            validate_breakdown(_normalize(root))

    def test_cycle_detected(self) -> None:
        root = _task(
            "root",
            children=[
                _task("a", depends_on=["b"]),
                _task("b", depends_on=["a"]),
            ],
        )
        with pytest.raises(BreakdownValidationError, match="Cyclic"):
            validate_breakdown(_normalize(root))

    def test_invalid_solid_prefix_fails(self) -> None:
        b = self._valid()
        b["acceptance_criteria"]["solid"] = "S is good."
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_missing_testing_coverage_phrase_fails(self) -> None:
        b = self._valid()
        b["acceptance_criteria"]["testing"] = (
            "Well-designed unit tests cover the behavior."
        )
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_too_many_functional_items_fails(self) -> None:
        b = self._valid()
        b["acceptance_criteria"]["functional"] = [
            f"check {i} passes assertion" for i in range(6)
        ]
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_duplicate_context_files_fails(self) -> None:
        b = self._valid()
        b["context_files"] = ["a.py", "a.py"]
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_wrong_target_model_class_fails(self) -> None:
        b = self._valid()
        b["target_model_class"] = "other"
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_token_limits_enforced(self) -> None:
        b = self._valid()
        b["estimated_context_tokens"] = 20000
        with pytest.raises(Exception):
            validate_breakdown(b)

    def test_colon_in_id_rejected(self) -> None:
        root = _task("root", children=[_task("bad:id")])
        with pytest.raises(Exception):
            validate_breakdown(_normalize(root))

    def test_missing_tasks_field_on_leaf_fails(self) -> None:
        b = self._valid()
        del b["tasks"]
        with pytest.raises(Exception):
            validate_breakdown(b)


# ---------------- private structural / graph checks ----------------


class TestValidateStructural:
    def _base(self) -> dict:
        return _normalize(
            _task("root", children=[_task("a"), _task("b", depends_on=["a"])])
        )

    def test_invalid_solid_prefix(self) -> None:
        b = self._base()
        b["tasks"][0]["acceptance_criteria"]["solid"] = "Solid stuff."
        with pytest.raises(BreakdownValidationError, match="solid.*prefix invalid"):
            _validate_structural(b)

    def test_invalid_yagni_kiss_prefix(self) -> None:
        b = self._base()
        b["tasks"][0]["acceptance_criteria"]["yagni_kiss"] = "Minimal design."
        with pytest.raises(BreakdownValidationError, match="yagni_kiss.*prefix invalid"):
            _validate_structural(b)

    def test_invalid_testing_prefix(self) -> None:
        b = self._base()
        b["tasks"][0]["acceptance_criteria"]["testing"] = "Tests exist."
        with pytest.raises(BreakdownValidationError, match="testing.*prefix invalid"):
            _validate_structural(b)

    def test_self_dependency(self) -> None:
        b = self._base()
        b["tasks"][0]["depends_on"] = ["a"]
        with pytest.raises(BreakdownValidationError, match="Self-dependency"):
            _validate_structural(b)

    def test_duplicate_ids_across_levels(self) -> None:
        b = _normalize(_task("root", children=[_task("x", children=[_task("root")])]))
        with pytest.raises(BreakdownValidationError, match="Duplicate task ids"):
            _validate_structural(b)


class TestValidateGraph:
    def _base(self) -> dict:
        return _normalize(
            _task("root", children=[_task("a"), _task("b", depends_on=["a"])])
        )

    def test_unknown_dependency(self) -> None:
        b = self._base()
        b["tasks"][1]["depends_on"] = ["t-99"]
        with pytest.raises(BreakdownValidationError, match="unknown task `t-99`"):
            _validate_graph(b)

    def test_cycle_detected(self) -> None:
        root = _task(
            "root",
            children=[
                _task("a", depends_on=["b"]),
                _task("b", depends_on=["a"]),
            ],
        )
        b = _normalize(root)
        with pytest.raises(BreakdownValidationError, match="Cyclic"):
            _validate_graph(b)

    def test_cross_subtree_chain_is_valid(self) -> None:
        root = _task(
            "root",
            children=[
                _task("left", children=[_task("l1")]),
                _task("right", children=[_task("r1", depends_on=["l1"])]),
            ],
        )
        _validate_graph(_normalize(root))

    def test_depends_on_descendant_rejected(self) -> None:
        """Parent listing its own descendant in depends_on is redundant with structural edge."""
        root = _task(
            "root",
            depends_on=["child"],
            children=[_task("child")],
        )
        b = _normalize(root)
        with pytest.raises(BreakdownValidationError, match="descendant"):
            _validate_graph(b)

    def test_depends_on_indirect_descendant_rejected(self) -> None:
        root = _task(
            "root",
            depends_on=["grand"],
            children=[_task("child", children=[_task("grand")])],
        )
        b = _normalize(root)
        with pytest.raises(BreakdownValidationError, match="descendant"):
            _validate_graph(b)

    def test_depends_on_ancestor_rejected(self) -> None:
        """Child depending on its ancestor creates a cycle with the structural edge."""
        root = _task(
            "root",
            children=[_task("child", depends_on=["root"])],
        )
        b = _normalize(root)
        with pytest.raises(BreakdownValidationError, match="ancestor"):
            _validate_graph(b)

    def test_structural_plus_depends_on_cycle_detected(self) -> None:
        """Cycle only visible when structural (child-before-parent) edges are included.

        Tree: root -> [a -> [a1], b -> [b1]]
        Deps: a1 depends_on b, b1 depends_on a
        Under beta: b waits for b1 waits for a waits for a1 waits for b (cycle).
        """
        root = _task(
            "root",
            children=[
                _task("a", children=[_task("a1", depends_on=["b"])]),
                _task("b", children=[_task("b1", depends_on=["a"])]),
            ],
        )
        b = _normalize(root)
        with pytest.raises(BreakdownValidationError, match="Cyclic"):
            _validate_graph(b)


class TestBuildRelationships:
    def test_flat_children_have_root_as_ancestor(self) -> None:
        root = _task("root", children=[_task("a"), _task("b")])
        nodes, descendants, ancestors = _build_relationships(_normalize(root))
        assert set(nodes) == {"root", "a", "b"}
        assert ancestors["a"] == {"root"}
        assert ancestors["root"] == set()
        assert descendants["root"] == {"a", "b"}
        assert descendants["a"] == set()

    def test_nested_ancestry(self) -> None:
        root = _task(
            "root", children=[_task("a", children=[_task("a1", children=[_task("a1x")])])]
        )
        _, descendants, ancestors = _build_relationships(_normalize(root))
        assert ancestors["a1x"] == {"root", "a", "a1"}
        assert descendants["root"] == {"a", "a1", "a1x"}
        assert descendants["a"] == {"a1", "a1x"}
