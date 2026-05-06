"""Protocol-based interfaces for dependency injection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, Protocol

if TYPE_CHECKING:
    from speedster.agent_client import AgentResponse


class EventStore(Protocol):
    """Durable append-only event store."""

    def append(
        self,
        task_id: str,
        event_type: str,
        role: str,
        model: str,
        message: str,
    ) -> dict: ...

    def replay(self) -> Iterator[dict]: ...

    def get_events_for_task(self, task_id: str) -> list[dict]: ...


class AgentGateway(Protocol):
    """Async HTTP client for agent communication."""

    async def work(
        self,
        url: str,
        payload: dict[str, Any],
        session_id: str | None = None,
    ) -> "AgentResponse": ...

    async def close(self) -> None: ...
