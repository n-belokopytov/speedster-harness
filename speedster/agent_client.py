"""HTTP client for communicating with agent containers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Structured response from an agent /work call."""

    session_id: str
    output: str
    model: str = ""
    tokens_used: int = 0
    latency_ms: int = 0
    error: str | None = None


@dataclass
class HealthResponse:
    """Structured response from an agent /health call."""

    status: str
    model: str = ""
    gpu_mem: str = ""


class AgentClient:
    """HTTP client for orchestrator -> agent communication.

    Handles connection pooling, timeouts, retries on transient errors,
    and health check integration. Use as an async context manager:

        async with AgentClient() as client:
            resp = await client.work(url, message)
    """

    def __init__(
        self,
        timeout: float = 600.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def __aenter__(self) -> AgentClient:
        self._client = await self._get_client()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def work(
        self,
        url: str,
        payload: dict[str, Any],
        session_id: str | None = None,
    ) -> AgentResponse:
        """Send a /work request to an agent container.

        Args:
            url: Agent base URL (e.g. "http://em-agent:8080")
            payload: Structured request data (task_id, description, etc.)
            session_id: Optional session identifier

        Returns:
            AgentResponse with output and metadata

        Raises:
            httpx.HTTPError: On persistent connection failures
            ValueError: On malformed agent responses
        """

        client = await self._get_client()
        request_data = dict(payload)
        if session_id:
            request_data["session_id"] = session_id

        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.post(
                    f"{url}/work",
                    json=request_data,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()

                return AgentResponse(
                    session_id=data.get("session_id", session_id or ""),
                    output=data.get("output", ""),
                    model=data.get("model", ""),
                    tokens_used=data.get("tokens_used", 0),
                    latency_ms=data.get("latency_ms", 0),
                )

            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Agent work attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )

                if attempt < self.max_retries:
                    delay = min(self.retry_delay * (2 ** attempt), 60)
                    await asyncio.sleep(delay)

        if last_error is not None:
            raise last_error
        raise httpx.HTTPError(
            f"Agent work failed after {self.max_retries} attempts"
        )

    async def health(self, url: str) -> HealthResponse:
        """Check agent health via /health endpoint.

        Args:
            url: Agent base URL

        Returns:
            HealthResponse with status and metadata
        """

        client = await self._get_client()
        try:
            response = await client.get(
                f"{url}/health",
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            return HealthResponse(
                status=data.get("status", "unknown"),
                model=data.get("model", ""),
                gpu_mem=data.get("gpu_mem", ""),
            )

        except httpx.HTTPError as exc:
            logger.error("Health check failed for %s: %s", url, exc)
            return HealthResponse(status="unhealthy")

    async def close(self) -> None:
        """Close the underlying HTTP client."""

        if self._client and not self._client.is_closed:
            await self._client.close()
