"""Append-only CSV event log for durable orchestrator state."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class EventLog:
    """Single-writer append-only CSV event store.

    Schema: seq,ts,task_id,event_type,role,model,message
    """

    HEADER = ["seq", "ts", "task_id", "event_type", "role", "model", "message"]

    def __init__(self, path: Path, fsync_on_append: bool = True):
        self.path = path
        self.fsync = fsync_on_append
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Create the log file with a header if it doesn't exist."""

        self.path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists() or self.path.stat().st_size == 0:
            with self.path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self.HEADER)

    def _next_seq(self) -> int:
        """Return the next sequence number based on existing rows."""

        if not self.path.exists():
            return 1

        seq = 1
        with self.path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    seq = max(seq, int(row["seq"]) + 1)
                except (ValueError, KeyError):
                    continue

        return seq

    def append(
        self,
        task_id: str,
        event_type: str,
        role: str,
        model: str,
        message: str,
    ) -> dict:
        """Append one event row and fsync for durability.

        Returns the event dict that was written.
        """

        seq = self._next_seq()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        event = {
            "seq": seq,
            "ts": ts,
            "task_id": task_id,
            "event_type": event_type,
            "role": role,
            "model": model,
            "message": message,
        }

        with self.path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.HEADER)
            writer.writerow(event)

            if self.fsync:
                f.flush()
                os.fsync(f.fileno())

        return event

    def replay(self) -> Iterator[dict]:
        """Yield events ordered by seq for state reconstruction."""

        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            events = list(reader)

        events.sort(key=lambda e: int(e.get("seq", 0)))

        for event in events:
            yield event

    def get_events_for_task(self, task_id: str) -> list[dict]:
        """Return all events for a specific task, ordered by seq."""

        return [e for e in self.replay() if e.get("task_id") == task_id]

    def get_latest_event_for_task(self, task_id: str) -> dict | None:
        """Return the most recent event for a specific task."""

        events = self.get_events_for_task(task_id)
        return events[-1] if events else None
