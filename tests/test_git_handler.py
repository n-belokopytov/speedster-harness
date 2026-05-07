"""Tests for speedster/git_handler.py - Orchestrator git operations."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from speedster.git_handler import GitHandler


class TestGitHandler:
    """Tests for GitHandler using real git repos in temp directories."""

    @pytest.fixture
    def work_dir(self) -> Path:
        """Create a temp directory for git handler."""

        tmp = Path(tempfile.mkdtemp())
        yield tmp
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    @pytest.fixture
    def handler(self, work_dir: Path) -> GitHandler:
        """Create a GitHandler with a mock git client."""

        handler = GitHandler(
            repo_url="https://example.com/test.git",
            work_dir=work_dir,
        )
        return handler

    def test_init_sets_attributes(self, handler: GitHandler) -> None:
        """Constructor should set repo_url and work_dir."""

        assert handler.repo_url == "https://example.com/test.git"

    def test_record_implementation(self, handler: GitHandler) -> None:
        """record_implementation should store branch and commit."""

        handler.record_implementation("task-001", "speedster/task-001", "abc123def456")

    def test_merge_to_main_no_branch_raises(self, handler: GitHandler) -> None:
        """merge_to_main should raise KeyError for unknown task."""

        with pytest.raises(KeyError, match="No branch recorded"):
            handler.merge_to_main("unknown-task")

    def test_cleanup(self, work_dir: Path) -> None:
        """cleanup should be callable without error."""

        handler = GitHandler(
            repo_url="https://example.com/test.git",
            work_dir=work_dir,
        )
        handler.cleanup()  # Should not raise


class TestGitHandlerWithRealGit:
    """Integration tests with real git repos."""

    @pytest.fixture
    def remote_repo(self) -> str:
        """Create a bare git repo with initial content."""

        tmp = Path(tempfile.mkdtemp())
        bare = tmp / "test-bare.git"
        bare.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

        # Create a working clone to push initial content
        work = tmp / "work-init"
        work.mkdir(exist_ok=True)
        subprocess.run(["git", "clone", str(bare), str(work)], check=True, capture_output=True)
        (work / "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "-C", str(work), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(work), "commit", "-m", "Initial commit"],
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
                **__import__("os").environ,
            },
        )
        subprocess.run(["git", "-C", str(work), "push"], check=True, capture_output=True)
        yield str(bare)
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    @pytest.fixture
    def handler(self, remote_repo: str, tmp_path: Path) -> GitHandler:
        """Create a GitHandler and setup the repo."""

        handler = GitHandler(
            repo_url=remote_repo,
            work_dir=tmp_path / "git-work",
        )
        handler.setup()
        return handler

    def test_setup_clones_repo(self, handler: GitHandler) -> None:
        """setup should clone the repository."""

        assert (handler.work_dir / "repo" / ".git").exists()

    def test_record_implementation_and_merge(self, handler: GitHandler) -> None:
        """record_implementation should store branch for later merge."""

        handler.record_implementation("task-001", "speedster/task-001", "abc123")
