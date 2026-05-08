"""Unit tests for AgentServer, config MOCK_MODE, and error propagation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.server import AgentServer, GitRequest, WorkRequest, WorkResponse


@pytest.fixture
def system_prompt_path(tmp_path: Path) -> Path:
    """Create a temporary system prompt file for all roles."""

    for role in ("em", "engineer", "qa"):
        prompt_file = tmp_path / f"{role}_system_prompt.txt"
        prompt_file.write_text(f"You are a {role} agent.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def cli_server(tmp_path):
    config = AgentConfig(role="engineer", model="default", host="127.0.0.1",
                         port=9999, repo_root=str(tmp_path), mock_mode=True)
    server = AgentServer(config)
    server._mock_mode = False
    server._system_prompt = "You are a test agent."
    server._workspace_root = tmp_path
    server._timeout_seconds = 10
    server._git_ssh_key = None
    return server


@pytest.fixture
def agent_server_nonmock(system_prompt_path: Path):
    """Create an AgentServer in non-mock mode with mocked GitClient."""

    mock_git = MagicMock()

    with patch("agent.server.GitClient", return_value=mock_git):
        config = AgentConfig(
            role="engineer",
            model="default",
            host="127.0.0.1",
            port=9999,
            repo_root=str(system_prompt_path),
            mock_mode=False,
            git_ssh_key="/run/secrets/github_ssh_key",
            repo_url="git@github.com:test/repo.git",
        )
        server = AgentServer(config)
        yield server


@pytest.fixture
def agent_server_mock(system_prompt_path: Path):
    """Create an AgentServer in mock mode."""

    config = AgentConfig(
        role="engineer",
        model="default",
        host="127.0.0.1",
        port=9999,
        repo_root=str(system_prompt_path),
        mock_mode=True,
    )
    server = AgentServer(config)
    yield server


# --- Tests migrated from test_agent_client.py ---


class TestAgentClientHappyPath:
    """Test successful PI CLI invocation."""

    def test_returns_output_correctly(self, cli_server: AgentServer) -> None:
        """Happy path: subprocess returns output, result is returned."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Here is the agent output\n"
        mock_result.stderr = ""

        with patch("agent.server.subprocess.run", return_value=mock_result):
            response = cli_server._process_message_via_cli("test message")

        assert response == "Here is the agent output"

    def test_system_prompt_and_message_in_command_args(
        self, cli_server: AgentServer
    ) -> None:
        """The pi command includes --append-system-prompt and the message."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK\n"
        mock_result.stderr = ""

        with patch("agent.server.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            cli_server._process_message_via_cli("hello world")

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
        self, cli_server: AgentServer
    ) -> None:
        """subprocess.TimeoutExpired raises RuntimeError."""
        with patch("agent.server.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["pi"], timeout=10
            )
            with pytest.raises(RuntimeError, match="timed out"):
                cli_server._process_message_via_cli("test")


class TestAgentClientNotFound:
    """Test CLI not found handling."""

    def test_cli_not_found_raises_runtime_error(
        self, cli_server: AgentServer
    ) -> None:
        """FileNotFoundError raises RuntimeError with helpful message."""
        with patch("agent.server.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with pytest.raises(RuntimeError, match="pi CLI not found"):
                cli_server._process_message_via_cli("test")


class TestAgentClientGitSSHKey:
    """Test GIT_SSH_COMMAND env injection."""

    def test_git_ssh_key_set_in_env(self, tmp_path: Path) -> None:
        """GIT_SSH_COMMAND is set in subprocess env when git_ssh_key is provided."""
        config = AgentConfig(
            role="engineer",
            model="default",
            host="127.0.0.1",
            port=9999,
            repo_root=str(tmp_path),
            mock_mode=True,
        )
        server = AgentServer(config)
        server._mock_mode = False
        server._system_prompt = "You are a test agent."
        server._workspace_root = tmp_path
        server._timeout_seconds = 10
        server._git_ssh_key = "/run/secrets/github_ssh_key"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK\n"
        mock_result.stderr = ""

        with patch("agent.server.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            server._process_message_via_cli("test")

        env = mock_run.call_args.kwargs["env"]
        assert "GIT_SSH_COMMAND" in env
        assert "/run/secrets/github_ssh_key" in env["GIT_SSH_COMMAND"]
        assert "StrictHostKeyChecking=no" in env["GIT_SSH_COMMAND"]

    def test_git_ssh_key_absent_not_in_env(self, cli_server: AgentServer) -> None:
        """GIT_SSH_COMMAND is not set in env when git_ssh_key is None."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK\n"
        mock_result.stderr = ""

        with patch("agent.server.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            cli_server._process_message_via_cli("test")

        env = mock_run.call_args.kwargs["env"]
        git_cmd = env.get("GIT_SSH_COMMAND")
        assert not git_cmd or "github" not in git_cmd


class TestAgentClientEmptyOutput:
    """Test empty output handling."""

    def test_empty_output_raises_runtime_error(
        self, cli_server: AgentServer
    ) -> None:
        """Empty stdout raises RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   \n"
        mock_result.stderr = ""

        with patch("agent.server.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="empty output"):
                cli_server._process_message_via_cli("test")


class TestAgentClientProcessError:
    """Test non-zero exit code handling."""

    def test_nonzero_exit_raises_runtime_error(
        self, cli_server: AgentServer
    ) -> None:
        """Non-zero return code raises RuntimeError with stderr."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "something went wrong"

        with patch("agent.server.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="exited with code 1"):
                cli_server._process_message_via_cli("test")


class TestAgentClientValidation:
    """Test input validation."""

    def test_empty_message_raises_value_error(
        self, cli_server: AgentServer
    ) -> None:
        """Empty message raises ValueError."""
        with pytest.raises(ValueError, match="required"):
            cli_server._process_message_via_cli("   ")

    def test_empty_system_prompt_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        """Empty system_prompt raises ValueError."""
        config = AgentConfig(
            role="engineer",
            model="default",
            host="127.0.0.1",
            port=9999,
            repo_root=str(tmp_path),
            mock_mode=True,
        )
        server = AgentServer(config)
        server._mock_mode = False
        server._system_prompt = ""
        server._workspace_root = tmp_path
        server._timeout_seconds = 10
        server._git_ssh_key = None

        with pytest.raises(ValueError, match="required"):
            server._process_message_via_cli("test message")


class TestSubprocessCwd:
    def test_subprocess_cwd_is_workspace_root(self, cli_server: AgentServer) -> None:
        mock_result = MagicMock(returncode=0, stdout="OK\n", stderr="")
        with patch("agent.server.subprocess.run", return_value=mock_result) as mock_run:
            cli_server._process_message_via_cli("test")
        assert mock_run.call_args.kwargs["cwd"] == str(cli_server._workspace_root)


class TestHealthCheck:
    def test_health_check_returns_ok(self, agent_server_mock: AgentServer) -> None:
        resp = agent_server_mock.health_check()
        assert resp.status == "ok"
        assert resp.model == "default"


class TestProcessMessageNonMock:
    """Test _process_message delegates to _process_message_via_cli in non-mock mode."""

    def test_agent_client_called(
        self, agent_server_nonmock: AgentServer
    ) -> None:
        """_process_message_via_cli is called with the user message."""

        import asyncio

        with patch.object(
            agent_server_nonmock,
            "_process_message_via_cli",
            return_value='{"result": "ok"}',
        ) as mock_method:
            asyncio.run(agent_server_nonmock._process_message("test message"))

        mock_method.assert_called_once_with("test message")

    def test_work_response_includes_session_id(
        self, agent_server_nonmock: AgentServer
    ) -> None:
        """WorkResponse carries a valid session_id."""

        import asyncio

        with patch.object(
            agent_server_nonmock,
            "_process_message_via_cli",
            return_value='{"result": "ok"}',
        ):
            request = WorkRequest(
                task_id="test-001",
                description="Test message",
            )

            response = asyncio.run(agent_server_nonmock.handle_work(request))

        assert isinstance(response, WorkResponse)
        assert response.session_id is not None
        assert len(response.session_id) > 0

    def test_agent_client_none_raises_runtime_error(
        self, system_prompt_path: Path
    ) -> None:
        """If _system_prompt is empty in non-mock mode, RuntimeError is raised."""

        config = AgentConfig(
            role="engineer",
            model="default",
            host="127.0.0.1",
            port=9999,
            repo_root=str(system_prompt_path),
            mock_mode=True,
        )
        server = AgentServer(config)
        server._mock_mode = False
        server._system_prompt = ""

        import asyncio

        with pytest.raises(RuntimeError, match="AgentClient not initialized"):
            asyncio.run(server._process_message("test"))


class TestHTTP500ErrorPropagation:
    """Test that /work returns 500 when _process_message_via_cli raises."""

    def test_work_endpoint_returns_500_on_agent_error(
        self, system_prompt_path: Path
    ) -> None:
        """When _process_message_via_cli raises RuntimeError, /work returns 500."""

        config = AgentConfig(
            role="engineer",
            model="default",
            host="127.0.0.1",
            port=9999,
            repo_root=str(system_prompt_path),
            mock_mode=True,
        )
        server = AgentServer(config)
        server._mock_mode = False
        server._system_prompt = "You are a test agent."
        server._workspace_root = system_prompt_path
        server._timeout_seconds = 10
        server._git_ssh_key = None

        with patch.object(
            server,
            "_process_message_via_cli",
            side_effect=RuntimeError("model unreachable"),
        ):
            import asyncio

            request = WorkRequest(
                task_id="test-001",
                description="Test message",
            )

            with pytest.raises(Exception) as exc_info:
                asyncio.run(server.handle_work(request))

            from fastapi import HTTPException

            assert isinstance(exc_info.value, HTTPException)
            assert exc_info.value.status_code == 500
            assert "model unreachable" in str(exc_info.value.detail)


class TestMockModeEnvVariable:
    """Test that MOCK_MODE environment variable toggles correctly."""

    def test_mock_mode_default_true(self) -> None:
        """Default MOCK_MODE=1 results in mock_mode=True."""

        with patch.dict(os.environ, {"MOCK_MODE": "1"}):
            config = AgentConfig()
            assert config.mock_mode is True

    def test_mock_mode_zero_is_false(self) -> None:
        """MOCK_MODE=0 results in mock_mode=False."""

        with patch.dict(os.environ, {"MOCK_MODE": "0"}):
            config = AgentConfig()
            assert config.mock_mode is False

    def test_mock_mode_empty_string_is_false(self) -> None:
        """MOCK_MODE='' (empty) results in mock_mode=False."""

        with patch.dict(os.environ, {"MOCK_MODE": ""}):
            config = AgentConfig()
            assert config.mock_mode is False

    def test_mock_mode_unset_defaults_true(self) -> None:
        """Unset MOCK_MODE defaults to 1 (True)."""

        env_copy = os.environ.copy()
        env_copy.pop("MOCK_MODE", None)

        with patch.dict(os.environ, env_copy, clear=True):
            config = AgentConfig()
            assert config.mock_mode is True

    def test_explicit_constructor_overrides_env(self) -> None:
        """Explicit mock_mode argument overrides environment variable."""

        with patch.dict(os.environ, {"MOCK_MODE": "1"}):
            config = AgentConfig(mock_mode=False)
            assert config.mock_mode is False


class TestServerGitClient:
    """Test GitClient creation and clone() in AgentServer.__init__."""

    def test_git_client_created_for_all_roles_with_ssh_and_url(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient is instantiated for any role when SSH key and repo URL are set."""

        for role in ("em", "engineer", "qa"):
            mock_git = MagicMock()

            with patch("agent.server.GitClient", return_value=mock_git) as MockGitClient:
                config = AgentConfig(
                    role=role,
                    model="default",
                    host="127.0.0.1",
                    port=9999,
                    repo_root=str(system_prompt_path),
                    mock_mode=False,
                    git_ssh_key="/run/secrets/github_ssh_key",
                    repo_url="git@github.com:test/repo.git",
                )
                AgentServer(config)

                MockGitClient.assert_called_once()
                call_kwargs = MockGitClient.call_args.kwargs
                assert call_kwargs["repo_url"] == "git@github.com:test/repo.git"
                assert str(call_kwargs["ssh_key_path"]) == "/run/secrets/github_ssh_key"
                assert str(call_kwargs["repo_root"]) == str(system_prompt_path / "repo")

    def test_git_client_clone_called_on_init(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient.clone() is called during AgentServer.__init__."""

        mock_git = MagicMock()

        with patch("agent.server.GitClient", return_value=mock_git):
            config = AgentConfig(
                role="engineer",
                model="default",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=False,
                git_ssh_key="/run/secrets/github_ssh_key",
                repo_url="git@github.com:test/repo.git",
            )
            AgentServer(config)

            mock_git.clone.assert_called_once()

    def test_agent_workspace_root_is_cloned_repo_all_roles(
        self, system_prompt_path: Path
    ) -> None:
        """Workspace_root points to cloned repo for all roles."""

        for role in ("em", "engineer", "qa"):
            mock_git = MagicMock()

            with patch("agent.server.GitClient", return_value=mock_git):
                config = AgentConfig(
                    role=role,
                    model="default",
                    host="127.0.0.1",
                    port=9999,
                    repo_root=str(system_prompt_path),
                    mock_mode=False,
                    git_ssh_key="/run/secrets/github_ssh_key",
                    repo_url="git@github.com:test/repo.git",
                )
                server = AgentServer(config)

                assert str(server._workspace_root) == str(system_prompt_path / "repo")

    def test_agent_workspace_root_is_repo_root_without_git(
        self, system_prompt_path: Path
    ) -> None:
        """Workspace_root stays as repo_root when no SSH key or repo URL."""

        with patch("agent.server.GitClient") as MockGitClient:
            config = AgentConfig(
                role="em",
                model="default",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=False,
            )
            server = AgentServer(config)

            assert str(server._workspace_root) == str(system_prompt_path)
            MockGitClient.assert_not_called()

    def test_git_client_not_created_without_ssh_key(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient is NOT created when git_ssh_key is not configured."""

        with patch("agent.server.GitClient") as MockGitClient:
            config = AgentConfig(
                role="engineer",
                model="default",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=False,
            )
            AgentServer(config)

            MockGitClient.assert_not_called()

    def test_git_client_not_created_without_repo_url(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient is NOT created when repo_url is not configured."""

        with patch("agent.server.GitClient") as MockGitClient:
            config = AgentConfig(
                role="engineer",
                model="default",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=False,
                git_ssh_key="/run/secrets/github_ssh_key",
            )
            AgentServer(config)

            MockGitClient.assert_not_called()

    def test_git_client_not_created_in_mock_mode(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient is NOT created when mock_mode is True."""

        with patch("agent.server.GitClient") as MockGitClient:
            config = AgentConfig(
                role="engineer",
                model="default",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=True,
                git_ssh_key="/run/secrets/github_ssh_key",
                repo_url="git@github.com:test/repo.git",
            )
            AgentServer(config)

            MockGitClient.assert_not_called()


class TestGitEndpoint:
    async def test_git_merge_success(self, agent_server_nonmock):
        server = agent_server_nonmock
        with patch.object(server._git_client, 'fetch'), \
             patch.object(server._git_client, 'checkout'), \
             patch.object(server._git_client, 'merge', return_value="abc123def456"), \
             patch.object(server._git_client, 'push'):
            result = await server.handle_git(
                GitRequest(action="merge", branch="feature", default_branch="main", message="test merge")
            )
        assert result.action == "merge"
        assert result.sha == "abc123def456"
        assert result.error is None

    async def test_git_merge_client_not_initialized(self, agent_server_mock):
        server = agent_server_mock
        result = await server.handle_git(
            GitRequest(action="merge", branch="feature")
        )
        assert result.error is not None
        assert "not initialized" in result.error

    async def test_git_unknown_action(self, agent_server_mock):
        server = agent_server_mock
        result = await server.handle_git(
            GitRequest(action="rebase", branch="feature")
        )
        assert result.error is not None
        assert "Unknown action" in result.error
