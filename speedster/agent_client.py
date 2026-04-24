"""HTTP client for communicating with agent containers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Structured response from an agent /work call."""

    session_id: str
    output: str
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
    and health check integration.
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
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def __del__(self) -> None:
        if hasattr(self, "_client"):
            self._client.close()

    def work(
        self,
        url: str,
        message: str,
        session_id: str | None = None,
    ) -> AgentResponse:
        """Send a /work request to an agent container.

        Args:
            url: Agent base URL (e.g. "http://em-agent:8080")
            message: The prompt/message to send
            session_id: Optional session identifier

        Returns:
            AgentResponse with output and metadata

        Raises:
            httpx.HTTPError: On persistent connection failures
            ValueError: On malformed agent responses
        """

        payload = {"message": message}
        if session_id:
            payload["session_id"] = session_id

        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.post(
                    f"{url}/work",
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()

                return AgentResponse(
                    session_id=data.get("session_id", session_id or ""),
                    output=data.get("output", ""),
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
                    import time

                    time.sleep(self.retry_delay * attempt)

        raise last_error or httpx.HTTPError(
            f"Agent work failed after {self.max_retries} attempts"
        )

    def health(self, url: str) -> HealthResponse:
        """Check agent health via /health endpoint.

        Args:
            url: Agent base URL

        Returns:
            HealthResponse with status and metadata
        """

        try:
            response = self._client.get(
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

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()
