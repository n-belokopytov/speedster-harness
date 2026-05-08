"""Tests for speedster/git_handler.py - Orchestrator git operations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from speedster.git_handler import GitHandler, GitHandlerError, GitMergeResult


class TestGitHandler:
    """Tests for GitHandler using mocked HTTP calls."""

    @pytest.fixture
    def handler(self) -> GitHandler:
        """Create a GitHandler."""

        return GitHandler(
            engineer_agent_url="http://localhost:8082",
            default_branch="main",
        )

    def test_init_sets_attributes(self, handler: GitHandler) -> None:
        """Constructor should set engineer_agent_url and default_branch."""

        assert handler.engineer_agent_url == "http://localhost:8082"
        assert handler.default_branch == "main"

    def test_record_implementation(self, handler: GitHandler) -> None:
        """record_implementation should store branch and commit."""

        handler.record_implementation("task-001", "speedster/task-001", "abc123def456")

    @pytest.mark.asyncio
    async def test_merge_to_main_no_branch_raises(self, handler: GitHandler) -> None:
        """merge_to_main should raise KeyError for unknown task."""

        with pytest.raises(KeyError, match="No branch recorded"):
            await handler.merge_to_main("unknown-task")

    def test_cleanup(self, handler: GitHandler) -> None:
        """cleanup should be callable without error."""

        handler.cleanup()  # Should not raise

    @pytest.mark.asyncio
    async def test_merge_to_main_success(self, handler: GitHandler) -> None:
        """merge_to_main should call the agent and return GitMergeResult."""

        handler.record_implementation("task-001", "speedster/task-001", "abc123")

        mock_response = MagicMock()
        mock_response.json.return_value = {"sha": "deadbeef123456", "error": None}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def post(self, *a, **kw):
                return mock_response

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                pass

        with patch("httpx.AsyncClient", FakeClient):
            result = await handler.merge_to_main("task-001")

        assert isinstance(result, GitMergeResult)
        assert result.sha == "deadbeef123456"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_merge_to_main_error_from_agent(self, handler: GitHandler) -> None:
        """merge_to_main should raise GitHandlerError when agent returns an error."""

        handler.record_implementation("task-001", "speedster/task-001", "abc123")

        mock_response = MagicMock()
        mock_response.json.return_value = {"sha": "", "error": "merge conflict"}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def post(self, *a, **kw):
                return mock_response

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                pass

        with patch("httpx.AsyncClient", FakeClient):
            with pytest.raises(GitHandlerError, match="merge conflict"):
                await handler.merge_to_main("task-001")
