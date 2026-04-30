"""Unit tests for AgentServer, config MOCK_MODE, and error propagation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.server import AgentServer, Session, WorkRequest, WorkResponse


@pytest.fixture
def system_prompt_path(tmp_path: Path) -> Path:
    """Create a temporary system prompt file for all roles."""

    for role in ("em", "engineer", "qa"):
        prompt_file = tmp_path / f"{role}_system_prompt.txt"
        prompt_file.write_text(f"You are a {role} agent.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def mock_acp_client():
    """Return a mock ACPClient instance."""

    mock = MagicMock()
    mock.process_message.return_value = MagicMock(
        output=json.dumps({"result": "ok"}),
        tokens_used=150,
        latency_ms=200,
    )
    return mock


@pytest.fixture
def agent_server_nonmock(system_prompt_path: Path, mock_acp_client: MagicMock):
    """Create an AgentServer in non-mock mode with a mocked ACPClient."""

    with patch("agent.server.ACPClient", return_value=mock_acp_client):
        config = AgentConfig(
            role="engineer",
            model="vllm/test",
            host="127.0.0.1",
            port=9999,
            repo_root=str(system_prompt_path),
            mock_mode=False,
        )
        server = AgentServer(config)
        yield server


@pytest.fixture
def agent_server_mock(system_prompt_path: Path):
    """Create an AgentServer in mock mode."""

    config = AgentConfig(
        role="engineer",
        model="vllm/test",
        host="127.0.0.1",
        port=9999,
        repo_root=str(system_prompt_path),
        mock_mode=True,
    )
    server = AgentServer(config)
    yield server


class TestProcessMessageNonMock:
    """Test _process_message delegates to ACPClient in non-mock mode."""

    def test_acp_client_called(self, agent_server_nonmock: AgentServer, mock_acp_client: MagicMock) -> None:
        """ACPClient.process_message is called with the user message."""

        session = Session(
            session_id="test-session",
            role="engineer",
            model="vllm/test",
            created_at=0.0,
            last_activity=0.0,
        )

        import asyncio

        asyncio.run(agent_server_nonmock._process_message(session, "test message"))

        mock_acp_client.process_message.assert_called_once_with("test message")

    def test_tokens_used_propagates_to_session(
        self, agent_server_nonmock: AgentServer, mock_acp_client: MagicMock
    ) -> None:
        """tokens_used from ACPResponse is stored on the session."""

        session = Session(
            session_id="test-session",
            role="engineer",
            model="vllm/test",
            created_at=0.0,
            last_activity=0.0,
        )

        import asyncio

        asyncio.run(agent_server_nonmock._process_message(session, "test message"))

        assert session._last_tokens == 150

    def test_latency_propagates_to_session(
        self, agent_server_nonmock: AgentServer, mock_acp_client: MagicMock
    ) -> None:
        """latency_ms from ACPResponse is stored on the session."""

        session = Session(
            session_id="test-session",
            role="engineer",
            model="vllm/test",
            created_at=0.0,
            last_activity=0.0,
        )

        import asyncio

        asyncio.run(agent_server_nonmock._process_message(session, "test message"))

        assert session._last_latency == 200

    def test_work_response_includes_tokens_and_latency(
        self, agent_server_nonmock: AgentServer, mock_acp_client: MagicMock
    ) -> None:
        """WorkResponse carries tokens_used and latency_ms from ACPClient."""

        request = WorkRequest(message="test message")

        import asyncio

        response = asyncio.run(agent_server_nonmock.handle_work(request))

        assert isinstance(response, WorkResponse)
        assert response.tokens_used == 150
        assert response.latency_ms >= 0

    def test_acp_client_none_raises_runtime_error(
        self, system_prompt_path: Path
    ) -> None:
        """If _acp_client is None in non-mock mode, RuntimeError is raised."""

        config = AgentConfig(
            role="engineer",
            model="vllm/test",
            host="127.0.0.1",
            port=9999,
            repo_root=str(system_prompt_path),
            mock_mode=False,
        )
        server = AgentServer(config)
        server._acp_client = None

        session = Session(
            session_id="test-session",
            role="engineer",
            model="vllm/test",
            created_at=0.0,
            last_activity=0.0,
        )

        import asyncio

        with pytest.raises(RuntimeError, match="ACPClient not initialized"):
            asyncio.run(server._process_message(session, "test"))


class TestHTTP500ErrorPropagation:
    """Test that /work returns 500 when ACPClient raises."""

    def test_work_endpoint_returns_500_on_acp_error(
        self, system_prompt_path: Path
    ) -> None:
        """When ACPClient.process_message raises RuntimeError, /work returns 500."""

        mock_client = MagicMock()
        mock_client.process_message.side_effect = RuntimeError("model unreachable")

        with patch("agent.server.ACPClient", return_value=mock_client):
            config = AgentConfig(
                role="engineer",
                model="vllm/test",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=False,
            )
            server = AgentServer(config)

        import asyncio

        request = WorkRequest(message="test message")

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

    def test_git_client_created_for_engineer_with_ssh_and_url(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient is instantiated for engineer role when SSH key and repo URL are set."""

        mock_git = MagicMock()
        mock_acp = MagicMock()

        with patch("agent.server.ACPClient", return_value=mock_acp), \
             patch("agent.server.GitClient", return_value=mock_git) as MockGitClient:
            config = AgentConfig(
                role="engineer",
                model="vllm/test",
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
        mock_acp = MagicMock()

        with patch("agent.server.ACPClient", return_value=mock_acp), \
             patch("agent.server.GitClient", return_value=mock_git):
            config = AgentConfig(
                role="engineer",
                model="vllm/test",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=False,
                git_ssh_key="/run/secrets/github_ssh_key",
                repo_url="git@github.com:test/repo.git",
            )
            AgentServer(config)

            mock_git.clone.assert_called_once()

    def test_git_client_not_created_for_em_role(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient is NOT created for non-engineer roles."""

        mock_acp = MagicMock()

        with patch("agent.server.ACPClient", return_value=mock_acp), \
             patch("agent.server.GitClient") as MockGitClient:
            config = AgentConfig(
                role="em",
                model="vllm/test",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=False,
                git_ssh_key="/run/secrets/github_ssh_key",
                repo_url="git@github.com:test/repo.git",
            )
            AgentServer(config)

            MockGitClient.assert_not_called()

    def test_git_client_not_created_without_ssh_key(
        self, system_prompt_path: Path
    ) -> None:
        """GitClient is NOT created when git_ssh_key is not configured."""

        mock_acp = MagicMock()

        with patch("agent.server.ACPClient", return_value=mock_acp), \
             patch("agent.server.GitClient") as MockGitClient:
            config = AgentConfig(
                role="engineer",
                model="vllm/test",
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

        mock_acp = MagicMock()

        with patch("agent.server.ACPClient", return_value=mock_acp), \
             patch("agent.server.GitClient") as MockGitClient:
            config = AgentConfig(
                role="engineer",
                model="vllm/test",
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
                model="vllm/test",
                host="127.0.0.1",
                port=9999,
                repo_root=str(system_prompt_path),
                mock_mode=True,
                git_ssh_key="/run/secrets/github_ssh_key",
                repo_url="git@github.com:test/repo.git",
            )
            AgentServer(config)

            MockGitClient.assert_not_called()
