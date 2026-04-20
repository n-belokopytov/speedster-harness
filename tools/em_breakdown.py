"""EM breakdown deterministic helpers.

This module is the single source of truth for the derived and deterministic
parts of the EM breakdown contract referenced by `prompts/em_system_prompt.txt`
and enforced by `schemas/em_breakdown.schema.json`.

It exposes three responsibilities, intentionally separated per SRP:

- `compute_parallel_groups` : derive `parallel_group` from `depends_on`.
- `normalize_breakdown`     : stable ordering and canonical field shape.
- `validate_breakdown`      : schema + structural + graph validation.

The CLIs in `tools/validate_em_breakdown.py` and
`tools/normalize_em_breakdown.py` wrap these functions.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "em_breakdown.schema.json"

_SOLID_PREFIX = "The implementation adheres to SOLID principles by "
_YAGNI_KISS_PREFIX = "The implementation adheres to YAGNI and KISS by "
_TESTING_PREFIX = "Well-designed unit tests cover "
_TESTING_REQUIRED_PHRASE = "minimum unit test coverage of 80%+ for touched modules."


class BreakdownValidationError(ValueError):
    """Raised when a breakdown fails schema, structural, or graph checks."""


def compute_parallel_groups(subtasks: list[dict[str, Any]]) -> dict[str, int]:
    """Derive `parallel_group` for each subtask from `depends_on`.

    Rule: `parallel_group = 0` if no dependencies, else
    `1 + max(parallel_group(dep))`. Detects cycles and unknown IDs.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for s in subtasks:
        sid = s.get("id")
        if not isinstance(sid, str) or not sid:
            raise BreakdownValidationError("Each subtask must have a non-empty string `id`.")
        if sid in by_id:
            raise BreakdownValidationError(f"Duplicate subtask id: {sid}")
        by_id[sid] = s

    group: dict[str, int] = {}

    def resolve(sid: str, stack: set[str]) -> int:
        if sid in group:
            return group[sid]
        if sid in stack:
            raise BreakdownValidationError(f"Cyclic dependency detected at `{sid}`.")
        stack.add(sid)
        deps = by_id[sid].get("depends_on", []) or []
        for dep in deps:
            if dep not in by_id:
                raise BreakdownValidationError(
                    f"Subtask `{sid}` depends on unknown subtask `{dep}`."
                )
        g = 0 if not deps else 1 + max(resolve(d, stack) for d in deps)
        stack.remove(sid)
        group[sid] = g
        return g

    for s in subtasks:
        resolve(s["id"], set())
    return group


def normalize_breakdown(breakdown: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy with stable ordering and deduped lists.

    - Recomputes `parallel_group` from `depends_on`.
    - Dedupes and sorts `depends_on` and `context_files`.
    - Sorts subtasks by `(parallel_group, id)`.
    - Re-numbers subtask IDs to `<task_id>-<n>` preserving the final order.
    """
    out = json.loads(json.dumps(breakdown))
    task_id = out.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise BreakdownValidationError("`task_id` must be a non-empty string.")
    subs = out.get("subtasks")
    if not isinstance(subs, list) or not subs:
        raise BreakdownValidationError("`subtasks` must be a non-empty list.")

    groups = compute_parallel_groups(subs)
    for s in subs:
        s["parallel_group"] = groups[s["id"]]
        s["depends_on"] = sorted(dict.fromkeys(s.get("depends_on", []) or []))
        s["context_files"] = sorted(dict.fromkeys(s.get("context_files", []) or []))

    subs.sort(key=lambda s: (s["parallel_group"], s["id"]))

    old_to_new: dict[str, str] = {}
    for i, s in enumerate(subs, start=1):
        old_to_new[s["id"]] = f"{task_id}-{i}"
    for s in subs:
        s["id"] = old_to_new[s["id"]]
        s["depends_on"] = sorted(old_to_new[d] for d in s["depends_on"])

    subs.sort(key=lambda s: (s["parallel_group"], s["id"]))
    out["subtasks"] = subs
    return out


def _validate_structural(breakdown: dict[str, Any]) -> None:
    """Structural checks that JSON Schema cannot fully express."""
    subs = breakdown["subtasks"]
    for s in subs:
        ac = s["acceptance_criteria"]
        if not ac["solid"].startswith(_SOLID_PREFIX):
            raise BreakdownValidationError(
                f"`acceptance_criteria.solid` prefix invalid in {s['id']}."
            )
        if not ac["yagni_kiss"].startswith(_YAGNI_KISS_PREFIX):
            raise BreakdownValidationError(
                f"`acceptance_criteria.yagni_kiss` prefix invalid in {s['id']}."
            )
        if not ac["testing"].startswith(_TESTING_PREFIX):
            raise BreakdownValidationError(
                f"`acceptance_criteria.testing` prefix invalid in {s['id']}."
            )
        if _TESTING_REQUIRED_PHRASE not in ac["testing"]:
            raise BreakdownValidationError(
                f"`acceptance_criteria.testing` missing required coverage phrase in {s['id']}."
            )
        if len(set(s["context_files"])) != len(s["context_files"]):
            raise BreakdownValidationError(f"Duplicate `context_files` in {s['id']}.")
        if s["id"] in s.get("depends_on", []):
            raise BreakdownValidationError(f"Self-dependency detected in {s['id']}.")


def _validate_graph(breakdown: dict[str, Any]) -> None:
    """Cycle detection, dependency existence, and group ordering checks."""
    subs = breakdown["subtasks"]
    ids = {s["id"] for s in subs}
    by_id = {s["id"]: s for s in subs}

    indegree = {sid: 0 for sid in ids}
    for s in subs:
        for dep in s["depends_on"]:
            if dep not in ids:
                raise BreakdownValidationError(
                    f"Subtask `{s['id']}` depends on unknown subtask `{dep}`."
                )
            indegree[s["id"]] += 1

    queue: deque[str] = deque([sid for sid, deg in indegree.items() if deg == 0])
    visited = 0
    remaining = dict(indegree)
    dependents: dict[str, list[str]] = {sid: [] for sid in ids}
    for s in subs:
        for dep in s["depends_on"]:
            dependents[dep].append(s["id"])

    while queue:
        node = queue.popleft()
        visited += 1
        for nxt in dependents[node]:
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                queue.append(nxt)
    if visited != len(ids):
        cyclic = sorted(sid for sid, deg in remaining.items() if deg > 0)
        raise BreakdownValidationError(f"Cyclic dependencies detected: {cyclic}")

    groups = compute_parallel_groups(subs)
    for s in subs:
        if s["parallel_group"] != groups[s["id"]]:
            raise BreakdownValidationError(
                f"`parallel_group` drift at `{s['id']}` "
                f"(got {s['parallel_group']}, expected {groups[s['id']]})."
            )
        for dep in s["depends_on"]:
            if s["parallel_group"] <= by_id[dep]["parallel_group"]:
                raise BreakdownValidationError(
                    f"Invalid group ordering: `{s['id']}` (group={s['parallel_group']}) "
                    f"must be > `{dep}` (group={by_id[dep]['parallel_group']})."
                )

    expected_order = sorted(subs, key=lambda x: (x["parallel_group"], x["id"]))
    if subs != expected_order:
        raise BreakdownValidationError(
            "Subtasks must be sorted by (parallel_group asc, id asc)."
        )


def _validate_json_schema(breakdown: dict[str, Any], schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `jsonschema`. Install with: pip install jsonschema"
        ) from exc
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=breakdown, schema=schema)


def validate_breakdown(
    breakdown: dict[str, Any],
    schema_path: Path | None = None,
) -> None:
    """Validate a breakdown end-to-end (schema + structural + graph)."""
    _validate_json_schema(breakdown, schema_path or DEFAULT_SCHEMA_PATH)
    _validate_structural(breakdown)
    _validate_graph(breakdown)


def load_breakdown(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise BreakdownValidationError("Top-level JSON value must be an object.")
    return data
