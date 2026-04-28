"""Unit tests for ACPClient subprocess wrapper.

Covers subprocess success, timeout, crash, JSON parse failure,
prompt building, and cleanup behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.acp_client import ACPClient, ACPResponse


@pytest.fixture
def system_prompt_path(tmp_path: Path) -> Path:
    """Create a temporary system prompt file."""

    prompt_file = tmp_path / "test_system_prompt.txt"
    prompt_file.write_text("You are a test agent.", encoding="utf-8")
    return prompt_file


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """Create a temporary workspace root."""

    return tmp_path


@pytest.fixture
def acp_client(system_prompt_path: Path, workspace_root: Path) -> ACPClient:
    """Create an ACPClient with test defaults."""

    return ACPClient(
        role="em",
        model="vllm/test-model",
        system_prompt_path=system_prompt_path,
        workspace_root=workspace_root,
        timeout_seconds=10,
    )


class TestACPClientPromptBuilding:
    """Test prompt construction logic."""

    def test_build_prompt_combines_system_and_user(
        self, acp_client: ACPClient
    ) -> None:
        """Full prompt contains system prompt, separator, and user message."""

        prompt = acp_client._build_prompt("Implement feature X")

        assert "You are a test agent." in prompt
        assert "### USER MESSAGE" in prompt
        assert "Implement feature X" in prompt

    def test_build_prompt_preserves_newlines(self, acp_client: ACPClient) -> None:
        """User message with newlines is preserved in the full prompt."""

        message = "Line 1\nLine 2\nLine 3"
        prompt = acp_client._build_prompt(message)

        assert "Line 1\nLine 2\nLine 3" in prompt


class TestACPClientParseOutput:
    """Test stdout parsing into ACPResponse."""

    def test_parse_valid_json_dict(self, acp_client: ACPClient) -> None:
        """Valid JSON dict is parsed and re-serialized."""

        raw = json.dumps({"id": "test", "status": "ok"})
        response = ACPClient._parse_output(raw, latency_ms=100)

        assert isinstance(response, ACPResponse)
        assert "id" in response.output
        assert response.latency_ms == 100
        assert response.tokens_used > 0

    def test_parse_valid_json_object(self, acp_client: ACPClient) -> None:
        """Valid JSON with nested structure is handled correctly."""

        raw = json.dumps({
            "id": "task-001",
            "tasks": [{"id": "sub-1", "tasks": []}],
        })
        response = ACPClient._parse_output(raw, latency_ms=200)

        assert "task-001" in response.output
        assert response.latency_ms == 200

    def test_parse_empty_output_raises(self, acp_client: ACPClient) -> None:
        """Empty stdout raises RuntimeError."""

        with pytest.raises(RuntimeError, match="empty output"):
            ACPClient._parse_output("", latency_ms=50)

    def test_parse_whitespace_only_raises(self, acp_client: ACPClient) -> None:
        """Whitespace-only stdout is treated as empty."""

        with pytest.raises(RuntimeError, match="empty output"):
            ACPClient._parse_output("   \n  ", latency_ms=50)

    def test_parse_invalid_json_raises(self, acp_client: ACPClient) -> None:
        """Non-JSON stdout raises RuntimeError with preview."""

        with pytest.raises(RuntimeError, match="not valid JSON"):
            ACPClient._parse_output("this is not json {", latency_ms=50)


class TestACPClientProcessMessage:
    """Test subprocess invocation and response handling."""

    def test_success_returns_acp_response(
        self, acp_client: ACPClient
    ) -> None:
        """Happy path: subprocess returns valid JSON, ACPResponse is returned."""

        mock_output = json.dumps({"result": "success"})

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=mock_output, stderr=""
            )

            response = acp_client.process_message("test message")

            assert isinstance(response, ACPResponse)
            assert "success" in response.output
            assert response.tokens_used > 0
            assert response.latency_ms >= 0

    def test_success_passes_correct_args(
        self, acp_client: ACPClient
    ) -> None:
        """Subprocess is called with opencode, model, and stdin args."""

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=json.dumps({"ok": True}), stderr=""
            )

            acp_client.process_message("test message")

            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert "opencode" in call_args.args[0]
            assert "--model" in call_args.args[0]
            assert "vllm/test-model" in call_args.args[0]
            assert "--stdin" in call_args.args[0]
            assert call_args.kwargs["input"] is not None
            assert "test message" in call_args.kwargs["input"]

    def test_timeout_raises_runtime_error(
        self, acp_client: ACPClient
    ) -> None:
        """Subprocess timeout raises RuntimeError with role info."""

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd="opencode", timeout=10
            )

            with pytest.raises(RuntimeError, match="timed out"):
                acp_client.process_message("test message")

    def test_subprocess_crash_raises_runtime_error(
        self, acp_client: ACPClient
    ) -> None:
        """Non-zero exit code raises RuntimeError with stderr."""

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="segfault"
            )

            with pytest.raises(RuntimeError, match="exited with code 1"):
                acp_client.process_message("test message")

    def test_cli_not_found_raises_runtime_error(
        self, acp_client: ACPClient
    ) -> None:
        """Missing opencode binary raises RuntimeError."""

        import subprocess as sp

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            with pytest.raises(RuntimeError, match="not found"):
                acp_client.process_message("test message")

    def test_invalid_json_from_subprocess_raises(
        self, acp_client: ACPClient
    ) -> None:
        """Non-JSON stdout from subprocess raises RuntimeError."""

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="not json", stderr=""
            )

            with pytest.raises(RuntimeError, match="not valid JSON"):
                acp_client.process_message("test message")

    def test_workspace_root_passed_to_subprocess(
        self, acp_client: ACPClient
    ) -> None:
        """Subprocess cwd is set to workspace_root."""

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=json.dumps({"ok": True}), stderr=""
            )

            acp_client.process_message("test")

            assert mock_run.call_args.kwargs["cwd"] == str(acp_client.workspace_root)


import subprocess  # noqa: E402


class TestACPClientInit:
    """Test ACPClient initialization."""

    def test_reads_system_prompt_on_init(self, system_prompt_path: Path, workspace_root: Path) -> None:
        """System prompt file is read during initialization."""

        client = ACPClient(
            role="em",
            model="vllm/test",
            system_prompt_path=system_prompt_path,
            workspace_root=workspace_root,
        )
        assert client._system_prompt == "You are a test agent."

    def test_stores_config_values(
        self, system_prompt_path: Path, workspace_root: Path
    ) -> None:
        """Configuration values are stored on the client instance."""

        client = ACPClient(
            role="engineer",
            model="vllm/custom-model",
            system_prompt_path=system_prompt_path,
            workspace_root=workspace_root,
            timeout_seconds=300,
        )

        assert client.role == "engineer"
        assert client.model == "vllm/custom-model"
        assert client.timeout_seconds == 300
        assert client.workspace_root == workspace_root


class TestACPClientGitSSHKey:
    """Test GIT_SSH_COMMAND env injection when git_ssh_key is configured."""

    def test_git_ssh_key_set_in_env(
        self, system_prompt_path: Path, workspace_root: Path
    ) -> None:
        """GIT_SSH_COMMAND is set in subprocess env when git_ssh_key is provided."""

        client = ACPClient(
            role="engineer",
            model="vllm/test",
            system_prompt_path=system_prompt_path,
            workspace_root=workspace_root,
            git_ssh_key="/run/secrets/github_ssh_key",
        )

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=json.dumps({"ok": True}), stderr=""
            )
            client.process_message("test")

            env = mock_run.call_args.kwargs["env"]
            assert "GIT_SSH_COMMAND" in env
            assert "/run/secrets/github_ssh_key" in env["GIT_SSH_COMMAND"]
            assert "StrictHostKeyChecking=no" in env["GIT_SSH_COMMAND"]

    def test_git_ssh_key_not_set_when_absent(
        self, acp_client: ACPClient
    ) -> None:
        """GIT_SSH_COMMAND is absent from env when git_ssh_key is None."""

        with patch("agent.acp_client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=json.dumps({"ok": True}), stderr=""
            )
            acp_client.process_message("test")

            env = mock_run.call_args.kwargs["env"]
            assert "GIT_SSH_COMMAND" not in env or not env.get("GIT_SSH_COMMAND")
