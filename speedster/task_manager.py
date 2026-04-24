"""Task input loading and management."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Task:
    """A task definition loaded from tasks/<id>/task.json."""

    id: str
    description: str
    priority: str = "medium"
    status: str = "pending"
    created_at: str = ""
    model_override: str | None = None
    context_dir: Path = field(default_factory=Path)
    breakdown: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def has_breakdown(self) -> bool:
        return self.breakdown is not None


class TaskManager:
    """Loads task definitions and manages breakdown persistence."""

    def __init__(self, task_dir: Path):
        self.task_dir = task_dir

    def load_task(self, task_id: str) -> Task:
        """Load a task definition from tasks/<id>/task.json."""

        task_path = self.task_dir / task_id / "task.json"

        if not task_path.exists():
            raise FileNotFoundError(f"Task file not found: {task_path}")

        with task_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        task = Task(
            id=data.get("id", task_id),
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", ""),
            model_override=data.get("model_override"),
            context_dir=self.task_dir / task_id / "context",
        )

        # Load breakdown if available
        breakdown_path = self.task_dir / task_id / "breakdown.json"
        if breakdown_path.exists():
            with breakdown_path.open("r", encoding="utf-8") as f:
                task.breakdown = json.load(f)

        return task

    def list_tasks(self) -> list[Task]:
        """List all task directories and load their definitions."""

        if not self.task_dir.exists():
            return []

        tasks = []
        for entry in sorted(self.task_dir.iterdir()):
            if entry.is_dir() and (entry / "task.json").exists():
                try:
                    tasks.append(self.load_task(entry.name))
                except (FileNotFoundError, json.JSONDecodeError):
                    continue

        return tasks

    def save_breakdown(self, task_id: str, breakdown: dict[str, Any]) -> Path:
        """Save an EM breakdown to tasks/<id>/breakdown.json."""

        breakdown_path = self.task_dir / task_id / "breakdown.json"
        breakdown_path.parent.mkdir(parents=True, exist_ok=True)

        with breakdown_path.open("w", encoding="utf-8") as f:
            json.dump(breakdown, f, indent=2, ensure_ascii=False)

        return breakdown_path
