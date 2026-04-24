"""Data structures for agent workflow results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepResult:
    """Result from running a single agent step."""

    role: str
    model: str
    output: str
    tokens_used: int = 0
    latency_ms: int = 0
    branch: str = ""
    commit_sha: str = ""
    approved: bool = False
    feedback: list[str] = field(default_factory=lambda: ["All criteria met"])
