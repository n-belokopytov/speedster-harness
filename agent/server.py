"""FastAPI HTTP server for agent containers.

Exposes /work and /health endpoints for orchestrator communication.
Wraps PI one-shot CLI invocations for model inference.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uvicorn
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.config import AgentConfig
from agent.git_client import GitClient, GitClientError

logger = logging.getLogger(__name__)


class WorkRequest(BaseModel):
    """Request body for /work endpoint."""

    task_id: str
    description: str
    priority: str = "medium"
    plan: str | None = None
    round_num: int = 1
    qa_feedback: list[str] | None = None
    requested_context: list[str] | None = None
    session_id: str | None = None


class WorkResponse(BaseModel):
    """Response from /work endpoint."""

    session_id: str
    output: str
    model: str
    tokens_used: int = 0
    latency_ms: int = 0


class HealthResponse(BaseModel):
    """Response from /health endpoint."""

    status: str
    model: str


class GitRequest(BaseModel):
    """Request body for /git endpoint."""

    action: str
    branch: str
    default_branch: str = "main"
    message: str = ""


class GitResponse(BaseModel):
    """Response from /git endpoint."""

    action: str
    sha: str = ""
    error: str | None = None


class AgentServer:
    """FastAPI server for agent containers.

    Handles work requests and provides health checks using
    one-shot PI CLI invocations.
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.app = FastAPI(title=f"{config.role} Agent", version="0.1.0")
        self._mock_mode = config.mock_mode

        self._git_client: GitClient | None = None

        if not self._mock_mode:
            prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
            system_prompt_path = prompts_dir / f"{config.role}_system_prompt.txt"
            system_prompt = system_prompt_path.read_text(encoding="utf-8")

            repo_path = None
            if config.git_ssh_key and config.repo_url:
                repo_path = Path(config.repo_root) / "repo"
                self._git_client = GitClient(
                    repo_url=config.repo_url,
                    repo_root=repo_path,
                    ssh_key_path=Path(config.git_ssh_key),
                )
                self._git_client.clone()

            self._model = config.model
            self._system_prompt = system_prompt
            self._workspace_root = repo_path or Path(config.repo_root)
            self._timeout_seconds = 600
            self._git_ssh_key = config.git_ssh_key
        else:
            self._model = config.model
            self._system_prompt = ""
            self._workspace_root = Path("/")
            self._timeout_seconds = 600
            self._git_ssh_key = None

        self._register_routes()

    def _register_routes(self) -> None:
        """Register HTTP routes."""

        @self.app.post("/work")
        async def work(request: WorkRequest) -> WorkResponse:
            return await self.handle_work(request)

        @self.app.get("/health")
        async def health() -> HealthResponse:
            return self.health_check()

        @self.app.post("/git")
        async def git(req: GitRequest) -> GitResponse:
            return await self.handle_git(req)

    async def handle_work(self, request: WorkRequest) -> WorkResponse:
        """Handle a /work request.

        Args:
            request: The structured work request

        Returns:
            WorkResponse with output and metadata
        """

        session_id = str(uuid.uuid4())
        message = self._build_message(request)

        try:
            output = await self._process_message(message)

            return WorkResponse(
                session_id=session_id,
                output=output,
                model=self.config.model,
                tokens_used=0,
                latency_ms=0,
            )

        except Exception as exc:
            logger.error("Work processing failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    def _build_message(self, request: WorkRequest) -> str:
        """Build the user message from structured request data.

        Args:
            request: The structured work request

        Returns:
            Formatted message string
        """

        role = self.config.role
        lines = [
            "## Task",
            f"ID: {request.task_id}",
            f"Description: {request.description}",
            f"Priority: {request.priority}",
            "",
        ]

        if role == "em":
            if request.requested_context:
                lines.append("## Context Requested by Engineer")
                lines.append(json.dumps(request.requested_context, indent=2))
                lines.append("")
            lines.append("Please produce a breakdown.json with implementation plan.")

        elif role == "engineer":
            if request.plan:
                lines.append("## Plan")
                lines.append(request.plan)
                lines.append("")
            if request.round_num > 1 and request.qa_feedback:
                lines.append("## QA Feedback from Previous Round")
                for item in request.qa_feedback:
                    lines.append(f"- {item}")
                lines.append("")
                lines.append("Please address the above feedback.")
            else:
                lines.append("Please implement the task per the plan.")

        elif role == "qa":
            if request.plan:
                lines.append(f"## Engineer Output (Round {request.round_num})")
                lines.append(request.plan)
                lines.append("")
            lines.append("Please review and produce a QA review with findings.")

        return "\n".join(lines)

    def _process_message_via_cli(self, message: str) -> str:
        """Process a message through the PI one-shot CLI.

        Args:
            message: The user message to process

        Returns:
            The agent's output

        Raises:
            ValueError: If system_prompt or message is empty
            RuntimeError: If PI CLI fails
        """

        if not self._system_prompt or not message.strip():
            raise ValueError("system_prompt and message are required")

        env = os.environ.copy()
        if self._git_ssh_key:
            env["GIT_SSH_COMMAND"] = f"ssh -i '{self._git_ssh_key}' -o StrictHostKeyChecking=no"

        try:
            result = subprocess.run(
                [
                    "pi", "-p", "--no-session",
                    "--model", self._model,
                    "--append-system-prompt", self._system_prompt,
                    message,
                ],
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env=env,
                cwd=str(self._workspace_root),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "pi CLI not found. Ensure @earendil-works/pi-coding-agent "
                "is installed and on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"PI timed out after {self._timeout_seconds}s") from exc

        if result.returncode != 0:
            raise RuntimeError(f"PI exited with code {result.returncode}: {result.stderr}")

        output = result.stdout.strip()
        if not output:
            raise RuntimeError("PI returned empty output")

        return output

    async def _process_message(self, message: str) -> str:
        """Process a message through PI CLI or mock.

        Args:
            message: The user message to process

        Returns:
            The agent's output
        """

        if self._mock_mode:
            return await self._mock_process(message)

        if not self._system_prompt:
            raise RuntimeError("AgentClient not initialized; mock_mode may be misconfigured")

        return await asyncio.to_thread(self._process_message_via_cli, message)

    async def _mock_process(self, message: str) -> str:
        """Mock processing for testing without PI CLI.

        Returns a valid JSON response based on the agent's role.

        Args:
            message: The user message

        Returns:
            Mock JSON output
        """

        role = self.config.role

        if role == "em":
            return json.dumps({
                "id": "task-001",
                "description": "Mock EM plan",
                "acceptance_criteria": {
                    "functional": ["Mock functional criterion"],
                    "solid": "The implementation adheres to SOLID principles by separating concerns.",
                    "yagni_kiss": "The implementation adheres to YAGNI and KISS by keeping the solution simple.",
                    "testing": "Well-designed unit tests cover the behavior, with minimum unit test coverage of 80%+ for touched modules.",
                },
                "context_files": ["mock/file.py"],
                "context_rationale": "Mock rationale",
                "depends_on": [],
                "estimated_context_tokens": 1000,
                "estimated_work_tokens": 5000,
                "complexity_level": "simple",
                "target_model_class": "mid-size-25B",
                "status": "pending",
                "qa_rounds": 0,
                "feedback": None,
                "tasks": [],
            })

        elif role == "engineer":
            return json.dumps({
                "task_id": "task-001",
                "status": "implemented",
                "branch": "speedster/task-001",
                "files_changed": ["mock/file.py"],
                "tests_added_or_updated": ["tests/test_mock.py"],
                "acceptance_evidence": {
                    "functional": [{"criterion": "Mock criterion", "evidence": "Test passes"}],
                    "solid": "Separation of concerns maintained",
                    "yagni_kiss": "Simple solution implemented",
                    "testing": "Unit tests added",
                },
                "assumptions": [],
                "notes": "",
                "blocked_reason": "",
                "requested_context": [],
            })

        elif role == "qa":
            return json.dumps({
                "task_id": "task-001",
                "status": "approved",
                "branch": "speedster/task-001",
                "commit": "abc123def456",
                "round": 1,
                "findings": {
                    "functional": [{"criterion": "Mock criterion", "verdict": "met", "evidence": "Verified"}],
                    "solid": {"verdict": "met", "evidence": "Good separation"},
                    "yagni_kiss": {"verdict": "met", "evidence": "Simple solution"},
                    "testing": {"verdict": "met", "evidence": "Tests added"},
                },
                "rejection_reasons": [],
                "notes": "",
            })

        return json.dumps({"status": "unknown", "output": "Mock response"})

    def health_check(self) -> HealthResponse:
        """Check agent health.

        Returns:
            HealthResponse with status and metadata
        """

        return HealthResponse(
            status="ok",
            model=self.config.model,
        )

    async def handle_git(self, req: GitRequest) -> GitResponse:
        """Handle a /git request for merge operations.

        Args:
            req: The structured git request

        Returns:
            GitResponse with sha or error
        """

        if req.action == "merge":
            if self._git_client is None:
                return GitResponse(action="merge", error="GitClient not initialized")
            try:
                self._git_client.fetch("origin", req.default_branch)
                self._git_client.checkout(f"origin/{req.default_branch}")
                sha = self._git_client.merge(req.branch, req.message or f"Merge {req.branch}")
                self._git_client.push(req.default_branch)
                return GitResponse(action="merge", sha=sha)
            except GitClientError as exc:
                return GitResponse(action="merge", error=str(exc))
        return GitResponse(action=req.action, error=f"Unknown action: {req.action}")

    def run(self) -> None:
        """Start the FastAPI server with uvicorn."""

        uvicorn.run(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level="info",
        )
