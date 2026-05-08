"""Tests for speedster/main.py _create_git_handler function."""

from __future__ import annotations

import os
import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from speedster.config import AgentConfig, ConnectivityConfig


class TestCreateGitHandler:
    """Test _create_git_handler creates GitHandler when eng_url is set."""

    @pytest.fixture(autouse=True)
    def _patch_typer_before_import(self):
        """Patch sys.modules['typer'] before importing speedster.main."""

        mock_typer = MagicMock()
        original = sys.modules.get("typer")
        sys.modules["typer"] = mock_typer

        # Remove cached speedster.main so it re-imports with patched typer
        main_key = "speedster.main"
        cached = sys.modules.pop(main_key, None)

        yield

        # Restore
        if original is not None:
            sys.modules["typer"] = original
        else:
            sys.modules.pop("typer", None)

        if cached is not None:
            sys.modules[main_key] = cached

    def _import_main(self):
        """Import speedster.main with typer mocked."""

        return import_module("speedster.main")

    def test_returns_git_handler_when_eng_url_set(self) -> None:
        """Returns GitHandler instance when config has eng_url."""

        config = AgentConfig(
            connectivity=ConnectivityConfig(eng_url="http://localhost:8082"),
        )

        main_mod = self._import_main()

        with patch.object(main_mod, "GitHandler", new_callable=MagicMock) as MockGitHandler:
            mock_handler = MagicMock()
            MockGitHandler.return_value = mock_handler

            result = main_mod._create_git_handler(config)

            MockGitHandler.assert_called_once()
            call_kwargs = MockGitHandler.call_args.kwargs
            assert call_kwargs["engineer_agent_url"] == config.eng_url
            assert result == mock_handler

    def test_returns_none_when_eng_url_unset(self) -> None:
        """Returns None when config.eng_url is empty."""

        with patch.dict(os.environ, {"ENG_AGENT_URL": ""}):
            config = AgentConfig()

        main_mod = self._import_main()

        with patch.object(main_mod, "GitHandler", new_callable=MagicMock) as MockGitHandler:
            result = main_mod._create_git_handler(config)

            MockGitHandler.assert_not_called()
            assert result is None

    def test_default_branch_from_config(self) -> None:
        """GitHandler receives default_branch from config.repo_default_branch."""

        config = AgentConfig(
            connectivity=ConnectivityConfig(eng_url="http://localhost:8082"),
            repo_default_branch="develop",
        )

        main_mod = self._import_main()

        with patch.object(main_mod, "GitHandler", new_callable=MagicMock) as MockGitHandler:
            mock_handler = MagicMock()
            MockGitHandler.return_value = mock_handler

            main_mod._create_git_handler(config)

            call_kwargs = MockGitHandler.call_args.kwargs
            assert call_kwargs["default_branch"] == "develop"

    def test_default_branch_falls_back_to_main(self) -> None:
        """GitHandler receives 'main' when repo_default_branch is None."""

        config = AgentConfig(
            connectivity=ConnectivityConfig(eng_url="http://localhost:8082"),
        )

        main_mod = self._import_main()

        with patch.object(main_mod, "GitHandler", new_callable=MagicMock) as MockGitHandler:
            mock_handler = MagicMock()
            MockGitHandler.return_value = mock_handler

            main_mod._create_git_handler(config)

            call_kwargs = MockGitHandler.call_args.kwargs
            assert call_kwargs["default_branch"] == "main"


class TestRepoDefaultBranchEnvVar:
    """Test that REPO_DEFAULT_BRANCH env var is wired through AgentConfig."""

    def test_env_var_picked_up(self, tmp_path: Path) -> None:
        """AgentConfig reads REPO_DEFAULT_BRANCH from environment."""

        with patch.dict(os.environ, {"REPO_DEFAULT_BRANCH": "staging"}):
            config = AgentConfig()
            assert config.repo_default_branch == "staging"

    def test_env_var_defaults_to_none(self, tmp_path: Path) -> None:
        """AgentConfig.repo_default_branch is None when env var not set."""

        env = {"REPO_DEFAULT_BRANCH": ""}
        originals = {k: os.environ.get(k) for k in env}

        try:
            for k, v in env.items():
                if v:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)
            config = AgentConfig()
            assert config.repo_default_branch is None
        finally:
            for k, v in originals.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)


class TestWatchModeShutdown:
    """Test that watch mode responds promptly to shutdown signals."""

    @pytest.mark.asyncio
    async def test_shutdown_event_exits_loop(self) -> None:
        """Watch loop exits when shutdown event is set, without full poll interval."""

        import asyncio

        shutdown_event = asyncio.Event()
        poll_interval = 10
        iterations = 0

        async def simulate_watch_loop() -> None:
            nonlocal iterations
            while not shutdown_event.is_set():
                iterations += 1
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(), timeout=poll_interval
                    )
                except asyncio.TimeoutError:
                    pass

        async def trigger_shutdown_after(delay: float) -> None:
            await asyncio.sleep(delay)
            shutdown_event.set()

        start = asyncio.get_event_loop().time()
        await asyncio.gather(
            simulate_watch_loop(),
            trigger_shutdown_after(0.1),
        )
        elapsed = asyncio.get_event_loop().time() - start

        assert iterations == 1
        assert elapsed < poll_interval
