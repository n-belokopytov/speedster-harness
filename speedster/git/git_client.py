"""Git client — shared between agent and orchestrator layers.

Handles clone, branch, commit, and push operations with SSH key auth.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Raised when a git operation fails."""


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
        self._ssh_agent_socket: str | None = None

    def _ssh_env(self) -> dict[str, str]:
        """Build environment dict with GIT_SSH_COMMAND when SSH key is set."""

        env = os.environ.copy()
        if self.ssh_key_path:
            env["GIT_SSH_COMMAND"] = f"ssh -i {self.ssh_key_path} -o StrictHostKeyChecking=no"
        return env

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

    def fetch(self, remote: str, ref: str) -> None:
        """Fetch a specific ref from a remote.

        Args:
            remote: Remote name (e.g., 'origin').
            ref: Branch or ref to fetch (e.g., 'main', 'speedster/task-001').

        Raises:
            GitError: If fetch fails.
        """

        self._git("fetch", remote, ref)

    def create_branch(self, branch_name: str) -> None:
        """Create and checkout a new branch from the default branch.

        Args:
            branch_name: Name of the branch to create.

        Raises:
            GitError: If branch creation fails.
        """

        self.fetch("origin", self.default_branch)
        self._git("checkout", "-B", branch_name, f"origin/{self.default_branch}")
        logger.info("Created branch %s from origin/%s", branch_name, self.default_branch)

    def stage_all(self) -> None:
        """Stage all changes in the working directory.

        Raises:
            GitError: If staging fails.
        """

        self._git("add", "-A")

    def commit(self, message: str) -> str:
        """Commit staged changes with the given message.

        Args:
            message: Commit message.

        Returns:
            Full SHA of the new commit.

        Raises:
            GitError: If commit fails.
        """

        status_result = self._git("status", "--porcelain")
        if not status_result.stdout.strip():
            logger.info("No changes to commit")
            return self.get_head_sha()

        self._git("commit", "-m", message)
        sha = self.get_head_sha()
        logger.info("Committed: %s (%s)", sha[:7], message)
        return sha

    def push(self, branch_name: str, force: bool = False) -> None:
        """Push branch to remote origin.

        Args:
            branch_name: Branch to push.
            force: If True, force push the branch.

        Raises:
            GitError: If push fails.
        """

        args = ["push", "origin", branch_name]
        if force:
            args.append("--force")

        self._git(*args)
        logger.info("Pushed branch %s to origin", branch_name)

    def get_head_sha(self) -> str:
        """Return the HEAD commit SHA.

        Returns:
            Full 40-character SHA.

        Raises:
            GitError: If HEAD SHA cannot be determined.
        """

        result = self._git("rev-parse", "HEAD")
        return result.stdout.strip()

    def get_diff(self, base_ref: str | None = None) -> str:
        """Get the diff for staged/unstaged changes.

        Args:
            base_ref: Optional base ref to diff against (e.g., origin/main).
                If None, diffs working tree against HEAD.

        Returns:
            Unified diff string.

        Raises:
            GitError: If diff fails.
        """

        if base_ref:
            result = self._git("diff", base_ref)
        else:
            result = self._git("diff", "HEAD")

        return result.stdout

    def get_branches(self) -> list[str]:
        """List local branch names.

        Returns:
            List of branch names.

        Raises:
            GitError: If branch listing fails.
        """

        result = self._git("branch")
        lines = result.stdout.strip().split("\n")
        return [line.replace("* ", "").strip() for line in lines if line.strip()]

    def checkout(self, ref: str) -> None:
        """Checkout a branch, tag, or commit.

        Args:
            ref: Branch name, tag, or commit SHA to checkout.

        Raises:
            GitError: If checkout fails.
        """

        self._git("checkout", ref)
        logger.info("Checked out %s", ref)

    def merge(self, branch: str, message: str | None = None) -> str:
        """Merge a branch into the current branch.

        Args:
            branch: Branch to merge.
            message: Optional merge commit message. If None, uses default.

        Returns:
            Full SHA of the resulting commit.

        Raises:
            GitError: If merge fails or conflicts arise.
        """

        args = ["merge", branch]
        if message:
            args.extend(["-m", message])

        self._git(*args)
        sha = self.get_head_sha()
        logger.info("Merged %s into current branch (%s)", branch, sha[:7])
        return sha

    def pull(self, branch: str | None = None) -> None:
        """Pull latest changes from remote.

        Args:
            branch: Optional branch to pull. If None, pulls current branch.

        Raises:
            GitError: If pull fails.
        """

        if branch:
            self._git("pull", "origin", branch)
        else:
            self._git("pull")

        logger.info("Pulled latest changes")

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
