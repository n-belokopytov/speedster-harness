"""Unit tests for AgentClient HTTP communication.

Covers work() response parsing (including model propagation),
retry behavior, health checks, and context manager lifecycle.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from speedster.agent_client import AgentClient


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response with the given JSON data."""

    mock = MagicMock()
    mock.status_code = status_code
    mock.raise_for_status = lambda: None
    mock.json = MagicMock(return_value=data)
    return mock


class TestAgentClientWork:
    """Test the /work endpoint client logic."""

    async def test_work_returns_all_fields(self) -> None:
        """All server response fields including model are propagated."""

        client = AgentClient()
        mock_resp = _mock_response({
            "session_id": "sess-123",
            "output": '{"status": "implemented"}',
            "model": "vllm/test-model",
            "tokens_used": 500,
            "latency_ms": 1200,
        })
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(post=AsyncMock(return_value=mock_resp))
            result = await client.work(
                "http://agent:8080",
                {"task_id": "task-001", "description": "test"},
            )

        assert result.session_id == "sess-123"
        assert '{"status": "implemented"}' in result.output
        assert result.model == "vllm/test-model"
        assert result.tokens_used == 500
        assert result.latency_ms == 1200
        assert result.error is None

    async def test_work_defaults_missing_optional_fields(self) -> None:
        """Missing optional fields in server response default gracefully."""

        client = AgentClient()
        mock_resp = _mock_response({
            "session_id": "sess-456",
            "output": "partial response",
        })
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(post=AsyncMock(return_value=mock_resp))
            result = await client.work(
                "http://agent:8080",
                {"task_id": "task-002"},
            )

        assert result.session_id == "sess-456"
        assert result.output == "partial response"
        assert result.model == ""
        assert result.tokens_used == 0
        assert result.latency_ms == 0

    async def test_work_passes_session_id(self) -> None:
        """Session ID is forwarded to the agent when provided."""

        client = AgentClient()
        mock_resp = _mock_response({
            "session_id": "sess-789",
            "output": "ok",
        })
        mock_post = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(post=mock_post)
            await client.work(
                "http://agent:8080",
                {"task_id": "task-003"},
                session_id="my-session",
            )

        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["session_id"] == "my-session"
        assert call_json["task_id"] == "task-003"

    async def test_work_retries_on_http_error(self) -> None:
        """Transient HTTP errors trigger retry up to max_retries times."""

        client = AgentClient(max_retries=3, retry_delay=0.01)
        success_resp = _mock_response({
            "session_id": "sess-retry",
            "output": "ok",
        })
        mock_post = AsyncMock(side_effect=[
            httpx.HTTPError("timeout"),
            httpx.HTTPError("timeout"),
            success_resp,
        ])
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(post=mock_post)
            result = await client.work(
                "http://agent:8080",
                {"task_id": "task-004"},
            )

        assert result.session_id == "sess-retry"
        assert mock_post.call_count == 3

    async def test_work_raises_after_max_retries(self) -> None:
        """After exhausting retries, the last HTTPError is raised."""

        client = AgentClient(max_retries=2, retry_delay=0.01)
        mock_post = AsyncMock(side_effect=httpx.HTTPError("server down"))
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(post=mock_post)
            with pytest.raises(httpx.HTTPError, match="server down"):
                await client.work(
                    "http://agent:8080",
                    {"task_id": "task-005"},
                )

    async def test_work_raises_on_4xx_response(self) -> None:
        """A 4xx response from the agent raises HTTPError."""

        client = AgentClient(max_retries=1, retry_delay=0.01)
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=None, response=mock_resp
        )
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(post=AsyncMock(return_value=mock_resp))
            with pytest.raises(httpx.HTTPStatusError):
                await client.work(
                    "http://agent:8080",
                    {"task_id": "task-006"},
                )


class TestAgentClientHealth:
    """Test the /health endpoint client logic."""

    async def test_health_returns_healthy(self) -> None:
        """Successful health check returns HealthResponse with status."""

        client = AgentClient()
        mock_resp = _mock_response({
            "status": "healthy",
            "model": "vllm/test",
            "gpu_mem": "45%",
        })
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(get=AsyncMock(return_value=mock_resp))
            result = await client.health("http://agent:8080")

        assert result.status == "healthy"
        assert result.model == "vllm/test"
        assert result.gpu_mem == "45%"

    async def test_health_returns_unhealthy_on_error(self) -> None:
        """HTTP error during health check returns unhealthy status."""

        client = AgentClient()
        with patch.object(client, "_get_client") as mock_get:
            mock_get.return_value = AsyncMock(
                get=AsyncMock(side_effect=httpx.ConnectError("connection refused"))
            )
            result = await client.health("http://agent:8080")

        assert result.status == "unhealthy"


class TestAgentClientLifecycle:
    """Test AgentClient initialization and context manager."""

    async def test_context_manager_opens_and_closes(self) -> None:
        """__aenter__ creates client, __aexit__ closes it."""

        async with AgentClient() as client:
            assert client._client is not None
            assert not client._client.is_closed

    async def test_close_is_idempotent(self) -> None:
        """Calling close() multiple times does not raise."""

        client = AgentClient()
        await client._get_client()
        await client.close()
        await client.close()

    async def test_get_client_reuses_existing(self) -> None:
        """Second call to _get_client returns the same instance."""

        client = AgentClient()
        c1 = await client._get_client()
        c2 = await client._get_client()
        assert c1 is c2

    async def test_get_client_reopens_after_close(self) -> None:
        """_get_client creates a new client after close()."""

        client = AgentClient()
        c1 = await client._get_client()
        await client.close()
        c2 = await client._get_client()
        assert c1 is not c2
        assert not c2.is_closed
