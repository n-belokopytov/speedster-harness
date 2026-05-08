"""EM breakdown deterministic helpers (recursive task tree).

This module is the single source of truth for the derived and deterministic
parts of the EM breakdown contract referenced by `prompts/em_system_prompt.txt`
and enforced by `schemas/em_breakdown.schema.json`.

`validate_breakdown` performs schema + structural + graph validation.

Model recap:
- The root JSON value IS a task; a task is `{ id, ..., tasks: [task, ...] }`.
- Every node carries the full implementation-ready fields.
- Every task — leaf or non-leaf — is dispatched to the Engineer as exactly
  one invocation. A non-leaf task is the *integration* step that runs after
  all its descendants have been implemented.
- Execution order is `(all descendants implemented) AND (all depends_on
  targets implemented)`. Parent/child edges are therefore implicit
  structural dependencies; `depends_on` must not name ancestors or
  descendants (redundant with, or cyclic against, the structural edge).
- The validator checks cycles over the combined graph of structural and
  `depends_on` edges.
- There is no `parallel_group`; execution order is derived by the orchestrator
  from the tree + `depends_on` when needed.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Iterable

from speedster.contracts.json_schema import validate_json_schema
from speedster.exceptions import BreakdownValidationError

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "em_breakdown.schema.json"

_SOLID_PREFIX = "The implementation adheres to SOLID principles by "
_YAGNI_KISS_PREFIX = "The implementation adheres to YAGNI and KISS by "
_TESTING_PREFIX = "Well-designed unit tests cover "
__all__ = [
    "BreakdownValidationError",
    "validate_breakdown",
]


def _iter_tasks(root: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield every task node in the tree in pre-order (root first)."""
    stack: list[dict[str, Any]] = [root]
    while stack:
        node = stack.pop()
        yield node
        children = node.get("tasks") or []
        for child in reversed(children):
            stack.append(child)


def _validate_structural(breakdown: dict[str, Any]) -> None:
    """Structural checks that JSON Schema cannot fully express."""
    ids: list[str] = []
    for node in _iter_tasks(breakdown):
        ac = node["acceptance_criteria"]
        if not ac["solid"].startswith(_SOLID_PREFIX):
            raise BreakdownValidationError(
                f"`acceptance_criteria.solid` prefix invalid in {node['id']}."
            )
        if not ac["yagni_kiss"].startswith(_YAGNI_KISS_PREFIX):
            raise BreakdownValidationError(
                f"`acceptance_criteria.yagni_kiss` prefix invalid in {node['id']}."
            )
        if not ac["testing"].startswith(_TESTING_PREFIX):
            raise BreakdownValidationError(
                f"`acceptance_criteria.testing` prefix invalid in {node['id']}."
            )
        if len(set(node["context_files"])) != len(node["context_files"]):
            raise BreakdownValidationError(f"Duplicate `context_files` in {node['id']}.")
        if node["id"] in (node.get("depends_on") or []):
            raise BreakdownValidationError(f"Self-dependency detected in {node['id']}.")
        ids.append(node["id"])

    seen: set[str] = set()
    duplicates: list[str] = []
    for i in ids:
        if i in seen:
            duplicates.append(i)
        else:
            seen.add(i)
    if duplicates:
        raise BreakdownValidationError(
            f"Duplicate task ids in tree: {sorted(set(duplicates))}"
        )


def _build_relationships(
    root: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], dict[str, set[str]]]:
    """Return (nodes_by_id, descendants_by_id, ancestors_by_id)."""
    nodes = {n["id"]: n for n in _iter_tasks(root)}

    parent_of: dict[str, str | None] = {root["id"]: None}
    for n in _iter_tasks(root):
        for child in n.get("tasks") or []:
            parent_of[child["id"]] = n["id"]

    ancestors: dict[str, set[str]] = {}
    for nid in nodes:
        anc: set[str] = set()
        p = parent_of.get(nid)
        while p is not None:
            anc.add(p)
            p = parent_of[p]
        ancestors[nid] = anc

    descendants: dict[str, set[str]] = {nid: set() for nid in nodes}
    for nid, ancs in ancestors.items():
        for a in ancs:
            descendants[a].add(nid)

    return nodes, descendants, ancestors


def _validate_graph(breakdown: dict[str, Any]) -> None:
    """Dependency-existence, self-loop, ancestry, and cycle checks.

    Under the execution semantics the orchestrator uses, each task is
    dispatched after:
      - every descendant has been implemented (structural edge), AND
      - every `depends_on` target has been implemented.

    We therefore reject:
      - `depends_on` referencing unknown ids
      - self-dependency
      - dependency on a descendant (redundant with the structural edge)
      - dependency on an ancestor (creates a cycle with the structural edge)
      - any cycle in the combined graph of structural + `depends_on` edges.
    """
    nodes, descendants, ancestors = _build_relationships(breakdown)

    for n in nodes.values():
        nid = n["id"]
        for dep in n.get("depends_on") or []:
            if dep not in nodes:
                raise BreakdownValidationError(
                    f"Task `{nid}` depends on unknown task `{dep}`."
                )
            if dep == nid:
                raise BreakdownValidationError(f"Self-dependency detected in {nid}.")
            if dep in descendants[nid]:
                raise BreakdownValidationError(
                    f"Task `{nid}` depends on its own descendant `{dep}` "
                    "(redundant with the structural child-before-parent edge)."
                )
            if dep in ancestors[nid]:
                raise BreakdownValidationError(
                    f"Task `{nid}` depends on its ancestor `{dep}` "
                    "(creates a cycle with the structural child-before-parent edge)."
                )

    indegree: dict[str, int] = {nid: 0 for nid in nodes}
    dependents: dict[str, list[str]] = {nid: [] for nid in nodes}
    for n in nodes.values():
        nid = n["id"]
        for child in n.get("tasks") or []:
            indegree[nid] += 1
            dependents[child["id"]].append(nid)
        for dep in n.get("depends_on") or []:
            indegree[nid] += 1
            dependents[dep].append(nid)

    queue: deque[str] = deque(sorted(nid for nid, deg in indegree.items() if deg == 0))
    remaining = dict(indegree)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for nxt in dependents[node]:
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                queue.append(nxt)
    if visited != len(nodes):
        cyclic = sorted(nid for nid, deg in remaining.items() if deg > 0)
        raise BreakdownValidationError(f"Cyclic dependencies detected: {cyclic}")


def validate_breakdown(
    breakdown: dict[str, Any],
    schema_path: Path | None = None,
) -> None:
    """Validate a breakdown end-to-end (schema + structural + graph)."""
    validate_json_schema(breakdown, schema_path or DEFAULT_SCHEMA_PATH)
    _validate_structural(breakdown)
    _validate_graph(breakdown)
