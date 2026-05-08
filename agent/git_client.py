"""Git client for agent containers.

Handles clone and branch operations with SSH key auth.
Each agent clones the target repo on startup and creates a
dedicated branch per task.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Raised when a git operation fails."""


# Alias used by server.py handle_git
GitClientError = GitError


class GitClient:
    """Wraps git CLI for branch-per-task workflow.

    Uses SSH key authentication when configured. Each agent clones
    the repo once and creates a dedicated branch per task.
    """

    def __init__(
        self,
        repo_url: str,
        repo_root: Path,
        ssh_key_path: Path | None = None,
        default_branch: str = "main",
    ):
        """Initialize GitClient.

        Args:
            repo_url: Remote repository URL (SSH format preferred).
            repo_root: Local path where the repo should be cloned.
            ssh_key_path: Path to SSH private key for auth.
            default_branch: Default branch name (usually main or master).
        """

        self.repo_url = repo_url
        self.repo_root = repo_root
        self.ssh_key_path = ssh_key_path
        self.default_branch = default_branch

    def _git(self, *args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git command in the repo root.

        Args:
            *args: Git subcommand and arguments.
            capture: Whether to capture stdout/stderr.

        Returns:
            CompletedProcess with stdout/stderr.

        Raises:
            GitError: If the git command returns non-zero.
        """

        cmd = ["git", "-C", str(self.repo_root), *args]

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                timeout=120,
                env=self._ssh_env(),
                cwd=str(self.repo_root),
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"Git command timed out: {' '.join(cmd)}") from exc
        except FileNotFoundError as exc:
            raise GitError("git CLI not found. Ensure git is installed and on PATH.") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip() or "no stderr output"
            raise GitError(
                f"Git command failed (exit {result.returncode}): {' '.join(args)}\n{stderr}"
            )

        return result

    def clone(self) -> None:
        """Clone the repository into repo_root.

        Skips if repo_root already contains a git repo.

        Raises:
            GitError: If clone fails.
        """

        if (self.repo_root / ".git").exists():
            logger.info("Repository already exists at %s, skipping clone", self.repo_root)
            return

        logger.info("Cloning %s into %s", self.repo_url, self.repo_root)
        self.repo_root.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                ["git", "clone", self.repo_url, str(self.repo_root)],
                capture_output=True,
                text=True,
                timeout=300,
                env=self._ssh_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"Clone timed out after 300s: {self.repo_url}") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip() or "no stderr output"
            raise GitError(f"Clone failed: {stderr}")

        logger.info("Clone successful")

    @staticmethod
    def get_branch_for_task(task_id: str) -> str:
        """Generate a branch name for a task.

        Args:
            task_id: The task identifier.

        Returns:
            Branch name in format speedster/<task-id>.
        """

        safe_id = task_id.replace("/", "-").replace(" ", "_")
        return f"speedster/{safe_id}"

    def fetch(self, remote: str, branch: str) -> None:
        """Fetch a branch from a remote."""
        self._git("fetch", remote, branch)

    def push(self, branch: str) -> None:
        """Push a branch to origin."""
        self._git("push", "origin", branch)

    def checkout(self, ref: str) -> None:
        """Checkout a ref."""
        self._git("checkout", ref)

    def merge(self, branch: str, message: str) -> str:
        """Merge a branch with a given message. Returns HEAD SHA."""
        self._git("merge", "-m", message, branch)
        head = self._git("rev-parse", "HEAD")
        return head.strip()

    def get_head_sha(self) -> str:
        """Return the SHA of HEAD."""
        sha = self._git("rev-parse", "HEAD")
        return sha.strip()

    def get_diff(self, branch_a: str, branch_b: str) -> str:
        """Return the diff between two branches."""
        diff = self._git("diff", f"{branch_a}..{branch_b}")
        return diff.strip()

    def _ssh_env(self) -> dict[str, str]:
        """Build environment dict with GIT_SSH_COMMAND when SSH key is set."""

        env = os.environ.copy()
        if self.ssh_key_path:
            env["GIT_SSH_COMMAND"] = f"ssh -i {self.ssh_key_path} -o StrictHostKeyChecking=no"
        return env
