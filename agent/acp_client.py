"""OpenCode ACP subprocess client.

Wraps the opencode CLI as a non-interactive subprocess for model inference.
The agent server delegates to this client when _mock_mode is disabled.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ACPResponse:
    """Structured result from a single ACP invocation."""

    output: str
    tokens_used: int
    latency_ms: int


class ACPClient:
    """Subprocess wrapper for the opencode CLI.

    Spawns the opencode CLI in non-interactive mode, sends a system prompt
    and user message via stdin, and captures the JSON response from stdout.
    """

    def __init__(
        self,
        role: str,
        model: str,
        system_prompt_path: Path,
        workspace_root: Path,
        timeout_seconds: int = 600,
    ):
        """Initialize ACPClient.

        Args:
            role: Agent role (em, engineer, qa).
            model: Model identifier (e.g., vllm/unsloth/Qwen3.6-35B).
            system_prompt_path: Path to the role's system prompt file.
            workspace_root: Absolute path to the working directory.
            timeout_seconds: Deadline for each subprocess invocation.
        """

        self.role = role
        self.model = model
        self.system_prompt_path = system_prompt_path
        self.workspace_root = workspace_root
        self.timeout_seconds = timeout_seconds

        self._system_prompt = system_prompt_path.read_text(encoding="utf-8")

    def process_message(self, message: str) -> ACPResponse:
        """Spawn opencode subprocess and return structured response.

        Args:
            message: The user message to send to the model.

        Returns:
            ACPResponse with output string, tokens_used, and latency_ms.

        Raises:
            RuntimeError: If subprocess times out, crashes, or returns
                non-JSON output.
        """

        start_time = time.time()

        full_prompt = self._build_prompt(message)

        try:
            result = subprocess.run(
                ["opencode", "--model", self.model, "--stdin"],
                input=full_prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                cwd=str(self.workspace_root),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"ACPClient subprocess timed out after "
                f"{self.timeout_seconds}s for role={self.role}"
            ) from exc
        except FileNotFoundError as exc:
            if str(exc.filename) == str(self.workspace_root):
                raise RuntimeError(
                    f"Workspace root does not exist: {self.workspace_root}"
                ) from exc
            raise RuntimeError(
                "opencode CLI not found. Ensure opencode is installed "
                "and on PATH."
            ) from exc

        latency_ms = int((time.time() - start_time) * 1000)

        if result.returncode != 0:
            stderr = result.stderr.strip() or "no stderr output"
            raise RuntimeError(
                f"ACPClient subprocess exited with code {result.returncode}: "
                f"{stderr}"
            )

        output = self._parse_output(result.stdout, latency_ms)
        return output

    def _build_prompt(self, message: str) -> str:
        """Combine system prompt and user message into full prompt.

        Args:
            message: The user message to append after the system prompt.

        Returns:
            Combined prompt string with system + user sections.
        """

        return f"{self._system_prompt}\n\n### USER MESSAGE\n{message}\n"

    @staticmethod
    def _parse_output(raw_output: str, latency_ms: int) -> ACPResponse:
        """Parse subprocess stdout into ACPResponse.

        Args:
            raw_output: Raw stdout from the opencode subprocess.
            latency_ms: Computed latency in milliseconds.

        Returns:
            ACPResponse with parsed output, token count, and latency.

        Raises:
            RuntimeError: If stdout cannot be parsed as JSON.
        """

        stripped = raw_output.strip()
        if not stripped:
            raise RuntimeError("ACPClient subprocess returned empty output")

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            preview = stripped[:200]
            raise RuntimeError(
                f"ACPClient output is not valid JSON: {preview}"
            ) from exc

        output = json.dumps(parsed)
        tokens_used = len(stripped.split())

        return ACPResponse(
            output=output,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )
