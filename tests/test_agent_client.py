"""Unit tests for AgentClient (one-shot PI CLI client).

Covers subprocess.run mocking for happy path, timeout, CLI not found,
git SSH key injection, empty output, process error, and argument passing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.agent_client import AgentClient, AgentResponse


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """Create a temporary workspace root."""
    return tmp_path


@pytest.fixture
def agent_client(workspace_root: Path) -> AgentClient:
    """Create an AgentClient with test defaults."""
    return AgentClient(
        model="default",
        system_prompt="You are a test agent.",
        workspace_root=workspace_root,
        timeout_seconds=10,
    )


# --- Tests ---


class TestAgentClientHappyPath:
    """Test successful PI CLI invocation."""

    def test_returns_output_correctly(self, agent_client: AgentClient) -> None:
        """Happy path: subprocess returns output, AgentResponse is returned."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Here is the agent output\n"
        mock_result.stderr = ""

        with patch("agent.agent_client.subprocess.run", return_value=mock_result):
            response = agent_client.process_message("test message")

        assert isinstance(response, AgentResponse)
        assert response.output == "Here is the agent output"

    def test_system_prompt_and_message_in_command_args(
        self, agent_client: AgentClient
    ) -> None:
        """The pi command includes --append-system-prompt and the message."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK\n"
        mock_result.stderr = ""

        with patch("agent.agent_client.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            agent_client.process_message("hello world")

        call_args = mock_run.call_args.args[0]
        assert "pi" in call_args
        assert "-p" in call_args
        assert "--no-session" in call_args
        assert "--model" in call_args
        assert "default" in call_args
        assert "--append-system-prompt" in call_args
        assert "You are a test agent." in call_args
        assert "hello world" in call_args


class TestAgentClientTimeout:
    """Test timeout handling."""

    def test_timeout_raises_runtime_error(
        self, agent_client: AgentClient
    ) -> None:
        """subprocess.TimeoutExpired raises RuntimeError."""
        with patch("agent.agent_client.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["pi"], timeout=10
            )
            with pytest.raises(RuntimeError, match="timed out"):
                agent_client.process_message("test")


class TestAgentClientNotFound:
    """Test CLI not found handling."""

    def test_cli_not_found_raises_runtime_error(
        self, agent_client: AgentClient
    ) -> None:
        """FileNotFoundError raises RuntimeError with helpful message."""
        with patch("agent.agent_client.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with pytest.raises(RuntimeError, match="pi CLI not found"):
                agent_client.process_message("test")


class TestAgentClientGitSSHKey:
    """Test GIT_SSH_COMMAND env injection."""

    def test_git_ssh_key_set_in_env(self, workspace_root: Path) -> None:
        """GIT_SSH_COMMAND is set in subprocess env when git_ssh_key is provided."""
        client = AgentClient(
            model="default",
            system_prompt="You are a test agent.",
            workspace_root=workspace_root,
            git_ssh_key="/run/secrets/github_ssh_key",
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK\n"
        mock_result.stderr = ""

        with patch("agent.agent_client.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            client.process_message("test")

        env = mock_run.call_args.kwargs["env"]
        assert "GIT_SSH_COMMAND" in env
        assert "/run/secrets/github_ssh_key" in env["GIT_SSH_COMMAND"]
        assert "StrictHostKeyChecking=no" in env["GIT_SSH_COMMAND"]

    def test_git_ssh_key_absent_not_in_env(self, agent_client: AgentClient) -> None:
        """GIT_SSH_COMMAND is not set in env when git_ssh_key is None."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK\n"
        mock_result.stderr = ""

        with patch("agent.agent_client.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            agent_client.process_message("test")

        env = mock_run.call_args.kwargs["env"]
        git_cmd = env.get("GIT_SSH_COMMAND")
        assert not git_cmd or "github" not in git_cmd


class TestAgentClientEmptyOutput:
    """Test empty output handling."""

    def test_empty_output_raises_runtime_error(
        self, agent_client: AgentClient
    ) -> None:
        """Empty stdout raises RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   \n"
        mock_result.stderr = ""

        with patch("agent.agent_client.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="empty output"):
                agent_client.process_message("test")


class TestAgentClientProcessError:
    """Test non-zero exit code handling."""

    def test_nonzero_exit_raises_runtime_error(
        self, agent_client: AgentClient
    ) -> None:
        """Non-zero return code raises RuntimeError with stderr."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "something went wrong"

        with patch("agent.agent_client.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="exited with code 1"):
                agent_client.process_message("test")


class TestAgentClientValidation:
    """Test input validation."""

    def test_empty_message_raises_value_error(
        self, agent_client: AgentClient
    ) -> None:
        """Empty message raises ValueError."""
        with pytest.raises(ValueError, match="required"):
            agent_client.process_message("   ")

    def test_empty_system_prompt_raises_value_error(
        self, workspace_root: Path
    ) -> None:
        """Empty system_prompt raises ValueError."""
        client = AgentClient(
            model="default",
            system_prompt="",
            workspace_root=workspace_root,
        )
        with pytest.raises(ValueError, match="required"):
            client.process_message("test message")
