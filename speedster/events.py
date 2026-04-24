"""Event type definitions and phase transition logic."""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    TASK_CREATED = "TaskCreated"
    PLANNING_COMPLETED = "PlanningCompleted"
    IMPLEMENTATION_COMPLETED = "ImplementationCompleted"
    REVIEW_PASSED = "ReviewPassed"
    REVIEW_FAILED = "ReviewFailed"
    CONTEXT_REQUESTED = "ContextRequested"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"


PHASE_TRANSITIONS: dict[EventType, str] = {
    EventType.TASK_CREATED: "pending",
    EventType.PLANNING_COMPLETED: "planning",
    EventType.IMPLEMENTATION_COMPLETED: "implementing",
    EventType.REVIEW_PASSED: "review",
    EventType.REVIEW_FAILED: "implementing",
    EventType.CONTEXT_REQUESTED: "planning",
    EventType.TASK_COMPLETED: "completed",
    EventType.TASK_FAILED: "failed",
}

TERMINAL_EVENTS = {EventType.TASK_COMPLETED, EventType.TASK_FAILED}
