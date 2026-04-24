"""State projection from event log replay.

Replays events.csv to reconstruct per-task state for resume and status
queries. Minimal implementation pulled forward from Iteration 2 to
support CLI `resume` and `status` commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from speedster.event_log import EventLog
from speedster.events import (
    PHASE_TRANSITIONS,
    TERMINAL_EVENTS,
    EventType,
)


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
        if self.is_terminal:
            return "done"

        if not self.last_event_type or self.last_event_type == EventType.TASK_CREATED:
            return "em"

        if self.last_event_type == EventType.PLANNING_COMPLETED:
            return "engineer"

        if self.last_event_type == EventType.IMPLEMENTATION_COMPLETED:
            return "qa"

        if self.last_event_type in (
            EventType.REVIEW_FAILED,
            EventType.CONTEXT_REQUESTED,
        ):
            return "engineer" if self.last_event_type == EventType.REVIEW_FAILED else "em"

        return "done"


class StateProjection:
    """Rebuilds per-task state by replaying the event log.

    On startup, the orchestrator replays events and resumes all
    non-terminal tasks from their last durable event.
    """

    def __init__(self, event_log: EventLog):
        self.event_log = event_log
        self._projections: dict[str, TaskProjection] | None = None

    def rebuild(self) -> dict[str, TaskProjection]:
        """Replay all events and return per-task state projections.

        Result is cached on first call. Call invalidate() to force
        a rebuild if the event log has been appended to.

        Returns:
            Dict mapping task_id to TaskProjection
        """

        if self._projections is not None:
            return self._projections

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

            etype = EventType(event_type)
            if etype in PHASE_TRANSITIONS:
                proj.phase = PHASE_TRANSITIONS[etype]
            if etype == EventType.IMPLEMENTATION_COMPLETED:
                proj.qa_rounds += 1
            if etype in TERMINAL_EVENTS:
                proj.is_terminal = True

        self._projections = projections
        return projections

    def invalidate(self) -> None:
        """Invalidate the cached projections to force a rebuild."""

        self._projections = None

    def get_non_terminal(self) -> list[TaskProjection]:
        """Return projections for tasks that are not yet in a terminal state."""

        return [p for p in self.rebuild().values() if not p.is_terminal]

    def get_terminal(self) -> list[TaskProjection]:
        """Return projections for tasks that have reached a terminal state."""

        return [p for p in self.rebuild().values() if p.is_terminal]

    def get_task(self, task_id: str) -> TaskProjection | None:
        """Return the projection for a specific task."""

        return self.rebuild().get(task_id)
