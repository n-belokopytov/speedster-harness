"""State projection from event log replay.

Replays events.csv to reconstruct per-task state for resume and status
queries. Minimal implementation pulled forward from Iteration 2 to
support CLI `resume` and `status` commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from speedster.event_log import EventLog


TERMINAL_EVENTS = {"TaskCompleted", "TaskFailed"}


@dataclass
class TaskProjection:
    """Reconstructed state for a single task from event log replay."""

    task_id: str
    phase: str  # "pending", "planning", "implementing", "review", "completed", "failed"
    event_types: list[str] = field(default_factory=list)
    last_event: str = ""
    last_event_type: str = ""
    qa_rounds: int = 0
    is_terminal: bool = False

    def next_step(self) -> str:
        """Return the next workflow step based on current phase.

        Returns:
            Step name: "em", "engineer", "qa", or "done"
        """

        if self.is_terminal:
            return "done"

        if not self.last_event_type or self.last_event_type == "TaskCreated":
            return "em"

        if self.last_event_type == "PlanningCompleted":
            return "engineer"

        if self.last_event_type == "ImplementationCompleted":
            return "qa"

        if self.last_event_type == "ReviewFailed":
            return "engineer"

        if self.last_event_type == "ContextRequested":
            return "em"

        return "done"


class StateProjection:
    """Rebuilds per-task state by replaying the event log.

    On startup, the orchestrator replays events and resumes all
    non-terminal tasks from their last durable event.
    """

    def __init__(self, event_log: EventLog):
        self.event_log = event_log

    def rebuild(self) -> dict[str, TaskProjection]:
        """Replay all events and return per-task state projections.

        Returns:
            Dict mapping task_id to TaskProjection
        """

        projections: dict[str, TaskProjection] = {}

        for event in self.event_log.replay():
            task_id = event.get("task_id", "")
            event_type = event.get("event_type", "")
            message = event.get("message", "")

            if task_id not in projections:
                projections[task_id] = TaskProjection(
                    task_id=task_id,
                    phase="pending",
                )

            proj = projections[task_id]
            proj.event_types.append(event_type)
            proj.last_event = message
            proj.last_event_type = event_type

            if event_type == "TaskCreated":
                proj.phase = "pending"
            elif event_type == "PlanningCompleted":
                proj.phase = "planning"
            elif event_type == "ImplementationCompleted":
                proj.phase = "implementing"
                proj.qa_rounds += 1
            elif event_type == "ReviewPassed":
                proj.phase = "review"
            elif event_type == "ReviewFailed":
                proj.phase = "implementing"
            elif event_type == "ContextRequested":
                proj.phase = "planning"
            elif event_type == "TaskCompleted":
                proj.phase = "completed"
                proj.is_terminal = True
            elif event_type == "TaskFailed":
                proj.phase = "failed"
                proj.is_terminal = True

        return projections

    def get_non_terminal(self) -> list[TaskProjection]:
        """Return projections for tasks that are not yet in a terminal state."""

        return [p for p in self.rebuild().values() if not p.is_terminal]

    def get_terminal(self) -> list[TaskProjection]:
        """Return projections for tasks that have reached a terminal state."""

        return [p for p in self.rebuild().values() if p.is_terminal]

    def get_task(self, task_id: str) -> TaskProjection | None:
        """Return the projection for a specific task."""

        return self.rebuild().get(task_id)
