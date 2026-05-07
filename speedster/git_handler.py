"""Git handler for orchestrator.

Manages branch-per-task workflow: clones repos, merges approved branches,
and retrieves diffs for QA context and audit trail.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from speedster.git.git_client import GitClient

logger = logging.getLogger(__name__)


class GitHandler:
    """Orchestrator-side git operations.

    Manages a shared clone of the target repository. Creates branches
    for tasks, merges approved work serially into the default branch,
    and provides diff retrieval for QA context.
    """

    def __init__(
        self,
        repo_url: str,
        work_dir: Path | None = None,
        ssh_key_path: Path | None = None,
        default_branch: str = "main",
    ):
        """Initialize GitHandler.

        Args:
            repo_url: Remote repository URL.
            work_dir: Base directory for repo clones. Uses temp dir if None.
            ssh_key_path: Path to SSH private key for auth.
            default_branch: Default branch name.
        """

        self.repo_url = repo_url
        self.ssh_key_path = ssh_key_path
        self.default_branch = default_branch

        if work_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="speedster-git-")
            self.work_dir = Path(self._temp_dir)
        else:
            self._temp_dir = None
            self.work_dir = work_dir

        self._repo_root = self.work_dir / "repo"
        self._git_client: GitClient | None = None
        self._task_branches: dict[str, str] = {}

    @property
    def git_client(self) -> GitClient:
        """Return the GitClient, cloning the repo if needed."""

        if self._git_client is None:
            self._git_client = GitClient(
                repo_url=self.repo_url,
                repo_root=self._repo_root,
                ssh_key_path=self.ssh_key_path,
                default_branch=self.default_branch,
            )
        return self._git_client

    def setup(self) -> None:
        """Clone the repository for orchestrator operations.

        Raises:
            GitError: If clone fails.
        """

        self.git_client.clone()

    def record_implementation(
        self, task_id: str, branch: str, commit_sha: str
    ) -> None:
        """Record engineer's branch and commit SHA for a task.

        Args:
            task_id: The task identifier.
            branch: Branch name where code was pushed.
            commit_sha: HEAD SHA of the implementation commit.
        """

        self._task_branches[task_id] = branch
        logger.info(
            "Recorded implementation for task %s: branch=%s, commit=%s",
            task_id,
            branch,
            commit_sha[:7] if commit_sha else "N/A",
        )

    def merge_to_main(
        self, task_id: str, merge_message: str | None = None
    ) -> str:
        """Merge an approved task branch into the default branch.

        Merges serially to ensure deterministic order. After merge,
        pushes to remote.

        Args:
            task_id: The task identifier.
            merge_message: Optional merge commit message.

        Returns:
            Full SHA of the merge commit.

        Raises:
            GitError: If merge or push fails (conflicts raise GitError).
            KeyError: If no branch is recorded for the task.
        """

        branch_name = self._task_branches.get(task_id)
        if not branch_name:
            raise KeyError(f"No branch recorded for task {task_id}")

        # Ensure we have latest default branch
        self.git_client.fetch("origin", self.default_branch)
        self.git_client.checkout(f"origin/{self.default_branch}")

        message = merge_message or f"Merge task {task_id}: {branch_name}"
        sha = self.git_client.merge(branch_name, message)

        # Push merged default branch to remote
        self.git_client.push(self.default_branch)
        logger.info(
            "Merged task %s (%s) into %s: %s",
            task_id,
            branch_name,
            self.default_branch,
            sha[:7],
        )

        return sha

    def cleanup(self) -> None:
        """Clean up temporary files if using a temp directory."""

        if self._temp_dir and Path(self._temp_dir).exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            logger.info("Cleaned up temporary git working directory")
