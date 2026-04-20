#!/usr/bin/env python3
"""Ad-hoc validator for EM breakdown JSON.

Runs two checks:
1) JSON Schema validation (`schemas/em_breakdown.schema.json`)
2) Graph-level validation (dependency existence, acyclicity, group ordering)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


class BreakdownValidationError(ValueError):
    """Raised when breakdown graph semantics are invalid."""


def validate_breakdown_graph(breakdown: dict[str, Any]) -> None:
    """Validate dependency semantics and parallel group ordering."""
    subtasks = breakdown.get("subtasks", [])
    if not isinstance(subtasks, list) or not subtasks:
        raise BreakdownValidationError("`subtasks` must be a non-empty list.")

    ids: list[str] = []
    subtask_by_id: dict[str, dict[str, Any]] = {}
    for st in subtasks:
        sid = st.get("id")
        if not isinstance(sid, str) or not sid:
            raise BreakdownValidationError(
                "Each subtask must have a non-empty string `id`."
            )
        if sid in subtask_by_id:
            raise BreakdownValidationError(f"Duplicate subtask id: {sid}")
        ids.append(sid)
        subtask_by_id[sid] = st

    id_set = set(ids)

    # Build graph dep -> dependent
    indegree = {sid: 0 for sid in ids}
    graph: dict[str, list[str]] = defaultdict(list)

    for sid in ids:
        deps = subtask_by_id[sid].get("depends_on", [])
        if not isinstance(deps, list):
            raise BreakdownValidationError(
                f"`depends_on` must be a list for subtask {sid}."
            )

        seen_local: set[str] = set()
        for dep in deps:
            if not isinstance(dep, str):
                raise BreakdownValidationError(
                    f"Dependency IDs must be strings in subtask {sid}."
                )
            if dep in seen_local:
                raise BreakdownValidationError(
                    f"Duplicate dependency `{dep}` in subtask {sid}."
                )
            seen_local.add(dep)

            if dep == sid:
                raise BreakdownValidationError(f"Self-dependency detected in {sid}.")
            if dep not in id_set:
                raise BreakdownValidationError(
                    f"Subtask {sid} depends on missing subtask `{dep}`."
                )

            graph[dep].append(sid)
            indegree[sid] += 1

        pg = subtask_by_id[sid].get("parallel_group")
        if not isinstance(pg, int) or pg < 0:
            raise BreakdownValidationError(
                f"`parallel_group` must be an integer >= 0 for subtask {sid}."
            )

    # Kahn's algorithm for cycle detection
    queue = deque([sid for sid in ids if indegree[sid] == 0])
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for nxt in graph[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if visited != len(ids):
        cyclic_nodes = [sid for sid, deg in indegree.items() if deg > 0]
        raise BreakdownValidationError(
            f"Cyclic dependencies detected among subtasks: {cyclic_nodes}"
        )

    # Dependent group must be strictly greater than dependency group
    for sid in ids:
        sid_group = subtask_by_id[sid]["parallel_group"]
        for dep in subtask_by_id[sid].get("depends_on", []):
            dep_group = subtask_by_id[dep]["parallel_group"]
            if sid_group <= dep_group:
                raise BreakdownValidationError(
                    f"Invalid parallel_group ordering: `{sid}` (group={sid_group}) "
                    f"depends on `{dep}` (group={dep_group}). "
                    "Expected dependent group > dependency group."
                )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise BreakdownValidationError("Top-level JSON value must be an object.")
    return data


def _validate_schema(payload: dict[str, Any], schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `jsonschema`. Install with: pip install jsonschema"
        ) from exc

    schema = _load_json(schema_path)
    jsonschema.validate(instance=payload, schema=schema)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate EM breakdown JSON using schema + graph checks."
    )
    parser.add_argument("breakdown", help="Path to breakdown JSON to validate.")
    parser.add_argument(
        "--schema",
        default="schemas/em_breakdown.schema.json",
        help="Path to JSON schema file.",
    )
    args = parser.parse_args()

    breakdown_path = Path(args.breakdown)
    schema_path = Path(args.schema)

    if not breakdown_path.exists():
        print(f"ERROR: breakdown file not found: {breakdown_path}", file=sys.stderr)
        return 2
    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        return 2

    try:
        payload = _load_json(breakdown_path)
        _validate_schema(payload, schema_path)
        validate_breakdown_graph(payload)
    except Exception as exc:  # noqa: BLE001 - ad-hoc CLI needs concise error output
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print("VALID: breakdown passes schema and graph checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
