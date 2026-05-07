"""Unit tests for the event log."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from speedster.event_log import EventLog


@pytest.fixture
def event_log_path(tmp_path: Path) -> Path:
    """Create a temporary path for the event log."""

    log_path = tmp_path / "state" / "events.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


@pytest.fixture
def event_log(event_log_path: Path) -> EventLog:
    """Create an event log instance."""

    return EventLog(event_log_path)


class TestEventLogInit:
    def test_creates_file_with_header(self, event_log_path: Path) -> None:
        EventLog(event_log_path)
        assert event_log_path.exists()

        with event_log_path.open("r", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == EventLog.HEADER

    def test_preserves_existing_file(self, event_log_path: Path) -> None:
        log1 = EventLog(event_log_path)
        log1.append("task-1", "TaskCreated", "orchestrator", "", "Test")

        log2 = EventLog(event_log_path)
        events = list(log2.replay())
        assert len(events) == 1

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        log_path = tmp_path / "nested" / "dir" / "events.csv"
        EventLog(log_path)
        assert log_path.exists()

    def test_loads_last_seq_on_init(self, event_log_path: Path) -> None:
        log1 = EventLog(event_log_path)
        log1.append("task-1", "TaskCreated", "orchestrator", "", "Test 1")
        log1.append("task-1", "PlanningCompleted", "em", "model", "Planned")

        log2 = EventLog(event_log_path)
        assert log2._last_seq == 2

    def test_next_seq_uses_cache(self, event_log_path: Path) -> None:
        log = EventLog(event_log_path)
        log.append("task-1", "Event1", "role", "model", "Msg 1")
        log.append("task-1", "Event2", "role", "model", "Msg 2")
        log.append("task-1", "Event3", "role", "model", "Msg 3")

        events = list(log.replay())
        seqs = [int(e["seq"]) for e in events]
        assert seqs == [1, 2, 3]
        assert log._last_seq == 3


class TestAppend:
    def test_append_single_event(self, event_log: EventLog) -> None:
        event = event_log.append(
            "task-001",
            "TaskCreated",
            "orchestrator",
            "",
            "Task accepted",
        )

        assert event["seq"] == 1
        assert event["task_id"] == "task-001"
        assert event["event_type"] == "TaskCreated"
        assert event["role"] == "orchestrator"
        assert "ts" in event

    def test_append_multiple_events(self, event_log: EventLog) -> None:
        event_log.append("task-001", "TaskCreated", "orchestrator", "", "Created")
        event_log.append("task-001", "PlanningCompleted", "em", "vllm/model", "Planned")

        events = list(event_log.replay())
        assert len(events) == 2
        assert int(events[0]["seq"]) == 1
        assert int(events[1]["seq"]) == 2

    def test_sequence_numbers_are_monotonic(self, event_log: EventLog) -> None:
        for i in range(5):
            event_log.append("task-001", f"Event{i}", "role", "model", f"Msg {i}")

        events = list(event_log.replay())
        seqs = [int(e["seq"]) for e in events]
        assert seqs == [1, 2, 3, 4, 5]

    def test_different_tasks(self, event_log: EventLog) -> None:
        event_log.append("task-001", "TaskCreated", "orchestrator", "", "Task 1")
        event_log.append("task-002", "TaskCreated", "orchestrator", "", "Task 2")

        events = list(event_log.replay())
        assert len(events) == 2
        assert events[0]["task_id"] == "task-001"
        assert events[1]["task_id"] == "task-002"


class TestReplay:
    def test_replay_returns_all_events(self, event_log: EventLog) -> None:
        for i in range(3):
            event_log.append("task-001", f"Event{i}", "role", "model", f"Msg {i}")

        events = list(event_log.replay())
        assert len(events) == 3

    def test_replay_ordered_by_seq(self, event_log: EventLog) -> None:
        event_log.append("task-002", "TaskCreated", "orchestrator", "", "Task 2")
        event_log.append("task-001", "TaskCreated", "orchestrator", "", "Task 1")

        events = list(event_log.replay())
        assert events[0]["task_id"] == "task-002"
        assert events[1]["task_id"] == "task-001"

    def test_empty_replay(self, event_log_path: Path) -> None:
        EventLog(event_log_path)
        log = EventLog(event_log_path)
        events = list(log.replay())
        assert events == []


class TestTaskQueries:
    def test_get_events_for_task(self, event_log: EventLog) -> None:
        event_log.append("task-001", "TaskCreated", "orchestrator", "", "Task 1")
        event_log.append("task-002", "TaskCreated", "orchestrator", "", "Task 2")
        event_log.append("task-001", "PlanningCompleted", "em", "model", "Planned")

        events = event_log.get_events_for_task("task-001")
        assert len(events) == 2
        assert all(e["task_id"] == "task-001" for e in events)

    def test_get_latest_event_for_task(self, event_log: EventLog) -> None:
        event_log.append("task-001", "TaskCreated", "orchestrator", "", "Task 1")
        event_log.append("task-001", "PlanningCompleted", "em", "model", "Planned")

        latest = event_log.get_latest_event_for_task("task-001")
        assert latest is not None
        assert latest["event_type"] == "PlanningCompleted"

    def test_get_latest_event_no_events(self, event_log: EventLog) -> None:
        latest = event_log.get_latest_event_for_task("nonexistent")
        assert latest is None


class TestDurability:
    def test_fsync_on_append(self, event_log_path: Path) -> None:
        log = EventLog(event_log_path, fsync_on_append=True)
        log.append("task-001", "TaskCreated", "orchestrator", "", "Test")

        events = list(log.replay())
        assert len(events) == 1

    def test_no_fsync_still_works(self, event_log_path: Path) -> None:
        log = EventLog(event_log_path, fsync_on_append=False)
        log.append("task-001", "TaskCreated", "orchestrator", "", "Test")

        events = list(log.replay())
        assert len(events) == 1
