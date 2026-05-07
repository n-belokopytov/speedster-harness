"""Tests for agent/git_client.py - Git operations for agent containers."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from agent.git_client import GitClient, GitError


def _init_test_repo(path: Path) -> str:
    """Create a bare git repo and return the path for clone."""

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)

    # Create a working clone to push initial content
    work = path.parent / "work-init"
    work.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", str(path), str(work)], check=True, capture_output=True)

    (work / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "Initial commit"],
        check=True,
        capture_output=True,
        env={"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com", **__import__("os").environ},
    )
    subprocess.run(["git", "-C", str(work), "push"], check=True, capture_output=True)
    return str(path)


class TestGitClient:
    """Tests for GitClient using real git repos in temp directories."""

    @pytest.fixture
    def remote_repo(self) -> str:
        """Create a bare git repo with initial content."""

        with tempfile.TemporaryDirectory() as tmp:
            yield _init_test_repo(Path(tmp) / "test-bare.git")

    @pytest.fixture
    def work_dir(self) -> Path:
        """Create a temp directory for working copy."""

        tmp = Path(tempfile.mkdtemp())
        yield tmp
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    @pytest.fixture
    def git_client(self, remote_repo: str, work_dir: Path) -> GitClient:
        """Create a GitClient and clone the repo."""

        client = GitClient(
            repo_url=remote_repo,
            repo_root=work_dir / "clone",
        )
        client.clone()
        return client

    def test_clone_creates_git_dir(self, git_client: GitClient) -> None:
        """Clone should create a .git directory."""

        assert (git_client.repo_root / ".git").exists()

    def test_clone_idempotent(self, git_client: GitClient) -> None:
        """Calling clone again should not raise."""

        git_client.clone()

    def test_get_branch_for_task(self) -> None:
        """Branch name should follow speedster/<task-id> format."""

        branch = GitClient.get_branch_for_task("task-001")
        assert branch == "speedster/task-001"

    def test_get_branch_for_task_sanitizes(self) -> None:
        """Branch name should sanitize special characters."""

        branch = GitClient.get_branch_for_task("task/with spaces")
        assert "/" not in branch or branch.startswith("speedster/")
        assert " " not in branch

    def test_get_head_sha(self, git_client: GitClient) -> None:
        """HEAD SHA should be a 40-character hex string."""

        sha = git_client.get_head_sha()
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_get_diff_no_changes(self, git_client: GitClient) -> None:
        """Diff with no changes should return empty string."""

        diff = git_client.get_diff()
        assert not diff.strip()

    def test_get_diff_with_changes(self, git_client: GitClient) -> None:
        """Diff with changes should return unified diff."""

        readme = git_client.repo_root / "README.md"
        readme.write_text(readme.read_text() + "\n# Added line\n")
        diff = git_client.get_diff()
        assert "Added line" in diff

    def test_fetch_updates_remote_refs(self, git_client: GitClient, remote_repo: str) -> None:
        """Fetch should retrieve refs from remote."""

        import subprocess

        work = Path(remote_repo).parent / "work-init"
        (work / "fetched_file.txt").write_text("fetched\n")
        subprocess.run(["git", "-C", str(work), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(work), "commit", "-m", "Add fetched file"],
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

        git_client.fetch("origin", git_client.default_branch)


class TestGitClientErrors:
    """Tests for GitClient error handling."""

    def test_git_error_message(self) -> None:
        """GitError should have a meaningful message."""

        err = GitError("test error message")
        assert "test error message" in str(err)
