"""Task input loading and status projection from event log."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from speedster.event_log import EventLog


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


@dataclass
class TaskStatus:
    """Current status projection for a task derived from event log."""

    task_id: str
    phase: str  # "pending", "planning", "implementing", "review", "completed", "failed"
    qa_rounds: int = 0
    last_event: str = ""
    last_error: str = ""


class TaskManager:
    """Loads task definitions and exposes status from event replay."""

    def __init__(self, task_dir: Path, event_log: EventLog | None = None):
        self.task_dir = task_dir
        self.event_log = event_log

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

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        """Derive current task status from event log replay."""

        if not self.event_log:
            return None

        events = self.event_log.get_events_for_task(task_id)
        if not events:
            return None

        phase = "pending"
        qa_rounds = 0
        last_event = ""
        last_error = ""

        for event in events:
            etype = event.get("event_type", "")
            message = event.get("message", "")

            if etype == "TaskCreated":
                phase = "pending"
            elif etype == "PlanningCompleted":
                phase = "planning"
            elif etype == "ImplementationCompleted":
                phase = "implementing"
                qa_rounds += 1
            elif etype == "ReviewPassed":
                phase = "review"
            elif etype == "ReviewFailed":
                phase = "implementing"  # loop back to engineer
                last_error = message
            elif etype == "TaskCompleted":
                phase = "completed"
            elif etype == "TaskFailed":
                phase = "failed"
                last_error = message

            last_event = etype

        return TaskStatus(
            task_id=task_id,
            phase=phase,
            qa_rounds=qa_rounds,
            last_event=last_event,
            last_error=last_error,
        )

    def save_breakdown(self, task_id: str, breakdown: dict[str, Any]) -> Path:
        """Save an EM breakdown to tasks/<id>/breakdown.json."""

        breakdown_path = self.task_dir / task_id / "breakdown.json"
        breakdown_path.parent.mkdir(parents=True, exist_ok=True)

        with breakdown_path.open("w", encoding="utf-8") as f:
            json.dump(breakdown, f, indent=2, ensure_ascii=False)

        return breakdown_path
