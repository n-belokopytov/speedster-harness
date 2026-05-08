"""One-shot PI CLI client for agent containers."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    output: str


class AgentClient:
    def __init__(
        self,
        model: str,
        system_prompt: str,
        workspace_root: Path,
        timeout_seconds: int = 600,
        git_ssh_key: str | None = None,
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.workspace_root = workspace_root
        self.timeout_seconds = timeout_seconds
        self.git_ssh_key = git_ssh_key

    def process_message(self, message: str) -> AgentResponse:
        if not self.system_prompt or not message.strip():
            raise ValueError("system_prompt and message are required")

        env = os.environ.copy()
        if self.git_ssh_key:
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self.git_ssh_key} -o StrictHostKeyChecking=no"
            )

        try:
            result = subprocess.run(
                [
                    "pi", "-p", "--no-session",
                    "--model", self.model,
                    "--append-system-prompt", self.system_prompt,
                    message,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
                cwd=str(self.workspace_root),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "pi CLI not found. Ensure @earendil-works/pi-coding-agent "
                "is installed and on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"PI timed out after {self.timeout_seconds}s"
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"PI exited with code {result.returncode}: {result.stderr}"
            )

        output = result.stdout.strip()
        if not output:
            raise RuntimeError("PI returned empty output")

        return AgentResponse(output=output)
