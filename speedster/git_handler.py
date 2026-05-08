"""Git handler for orchestrator.

Delegates git operations to the engineer agent's /git endpoint.
Tracks branch-per-task mapping in memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


class GitHandlerError(Exception):
    pass


@dataclass
class GitMergeResult:
    sha: str
    error: str | None = None


class GitHandler:
    def __init__(
        self,
        engineer_agent_url: str,
        default_branch: str = "main",
    ):
        self.engineer_agent_url = engineer_agent_url
        self.default_branch = default_branch
        self._task_branches: dict[str, str] = {}

    def record_implementation(self, task_id: str, branch: str, commit_sha: str) -> None:
        self._task_branches[task_id] = branch
        logger.info(
            "Recorded implementation for task %s: branch=%s, commit=%s",
            task_id,
            branch,
            commit_sha[:7] if commit_sha else "N/A",
        )

    async def merge_to_main(
        self, task_id: str, merge_message: str | None = None
    ) -> GitMergeResult:
        branch_name = self._task_branches.get(task_id)
        if not branch_name:
            raise KeyError(f"No branch recorded for task {task_id}")

        message = merge_message or f"Merge task {task_id}: {branch_name}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.engineer_agent_url}/git",
                json={
                    "action": "merge",
                    "branch": branch_name,
                    "default_branch": self.default_branch,
                    "message": message,
                },
            )
            data = resp.json()

        if data.get("error"):
            raise GitHandlerError(data["error"])

        sha = data.get("sha", "")
        logger.info(
            "Merged task %s (%s) into %s: %s",
            task_id,
            branch_name,
            self.default_branch,
            sha[:7] if sha else "N/A",
        )
        return GitMergeResult(sha=sha)

    def cleanup(self) -> None:
        pass
