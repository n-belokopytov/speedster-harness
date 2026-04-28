"""Tests for speedster/main.py _create_git_handler function."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from speedster.config import AgentConfig


class TestCreateGitHandler:
    """Test _create_git_handler creates GitHandler when repo_url is set."""

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

    def test_returns_git_handler_when_repo_url_set(self) -> None:
        """Returns GitHandler instance when config has repo_url."""

        config = AgentConfig(
            repo_url="git@github.com:test/repo.git",
            git_ssh_key="/run/secrets/github_ssh_key",
        )

        main_mod = self._import_main()

        with patch.object(main_mod, "GitHandler", new_callable=MagicMock) as MockGitHandler:
            mock_handler = MagicMock()
            MockGitHandler.return_value = mock_handler

            result = main_mod._create_git_handler(config)

            MockGitHandler.assert_called_once()
            call_kwargs = MockGitHandler.call_args.kwargs
            assert call_kwargs["repo_url"] == "git@github.com:test/repo.git"
            assert str(call_kwargs["ssh_key_path"]) == "/run/secrets/github_ssh_key"
            mock_handler.setup.assert_called_once()
            assert result == mock_handler

    def test_returns_none_when_repo_url_unset(self) -> None:
        """Returns None when config.repo_url is not set."""

        config = AgentConfig()
        main_mod = self._import_main()

        with patch.object(main_mod, "GitHandler", new_callable=MagicMock) as MockGitHandler:
            result = main_mod._create_git_handler(config)

            MockGitHandler.assert_not_called()
            assert result is None

    def test_ssh_key_path_none_when_not_configured(self) -> None:
        """ssh_key_path is None when git_ssh_key is not configured."""

        config = AgentConfig(
            repo_url="git@github.com:test/repo.git",
        )

        main_mod = self._import_main()

        with patch.object(main_mod, "GitHandler", new_callable=MagicMock) as MockGitHandler:
            mock_handler = MagicMock()
            MockGitHandler.return_value = mock_handler

            main_mod._create_git_handler(config)

            call_kwargs = MockGitHandler.call_args.kwargs
            assert call_kwargs["ssh_key_path"] is None
