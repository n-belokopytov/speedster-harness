"""FastAPI HTTP server for agent containers.

Exposes /work and /health endpoints for orchestrator communication.
Wraps OpenCode ACP calls with session handling and token tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.acp_client import ACPClient, ACPResponse
from agent.config import AgentConfig
from speedster.git.git_client import GitClient

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
    gpu_mem: str = ""


@dataclass
class Session:
    """Active agent session state."""

    session_id: str
    role: str
    model: str
    created_at: float
    last_activity: float
    messages: list[dict[str, str]] = None
    _last_tokens: int = 0
    _last_latency: int = 0

    def __post_init__(self):
        if self.messages is None:
            self.messages = []


class AgentServer:
    """FastAPI server for agent containers.

    Manages sessions, handles work requests, and provides health checks.
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.app = FastAPI(title=f"{config.role} Agent", version="0.1.0")
        self._sessions: dict[str, Session] = {}
        self._mock_mode = config.mock_mode

        self._acp_client: ACPClient | None = None
        self._git_client: GitClient | None = None

        if not self._mock_mode:
            prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
            system_prompt_path = prompts_dir / f"{config.role}_system_prompt.txt"
            self._acp_client = ACPClient(
                role=config.role,
                model=config.model,
                system_prompt_path=system_prompt_path,
                workspace_root=Path(config.repo_root),
                git_ssh_key=config.git_ssh_key,
            )

            if config.role == "engineer" and config.git_ssh_key and config.repo_url:
                self._git_client = GitClient(
                    repo_url=config.repo_url,
                    repo_root=Path(config.repo_root),
                    ssh_key_path=Path(config.git_ssh_key),
                )
                self._git_client.clone()

        self._register_routes()

    def _register_routes(self) -> None:
        """Register HTTP routes."""

        @self.app.post("/work")
        async def work(request: WorkRequest) -> WorkResponse:
            return await self.handle_work(request)

        @self.app.get("/health")
        async def health() -> HealthResponse:
            return self.health_check()

    async def handle_work(self, request: WorkRequest) -> WorkResponse:
        """Handle a /work request.

        Args:
            request: The structured work request

        Returns:
            WorkResponse with output and metadata
        """

        session_id = request.session_id or str(uuid.uuid4())
        start_time = time.time()

        # Get or create session
        session = self._sessions.get(session_id)
        if not session:
            session = Session(
                session_id=session_id,
                role=self.config.role,
                model=self.config.model,
                created_at=start_time,
                last_activity=start_time,
            )
            self._sessions[session_id] = session

        session.last_activity = start_time
        message = self._build_message(request)
        session.messages.append({"role": "user", "content": message})

        try:
            output = await self._process_message(session, message)
            latency_ms = int((time.time() - start_time) * 1000)

            if session._last_tokens > 0:
                tokens_used = session._last_tokens
            else:
                tokens_used = len(output.split())

            return WorkResponse(
                session_id=session_id,
                output=output,
                model=self.config.model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
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

    async def _process_message(
        self, session: Session, message: str
    ) -> str:
        """Process a message through OpenCode ACP or mock.

        Args:
            session: The active session
            message: The user message to process

        Returns:
            The agent's output
        """

        if self._mock_mode:
            return await self._mock_process(session, message)

        if self._acp_client is None:
            raise RuntimeError("ACPClient not initialized; mock_mode may be misconfigured")

        response: ACPResponse = self._acp_client.process_message(message)
        session._last_tokens = response.tokens_used
        session._last_latency = response.latency_ms
        return response.output

    async def _mock_process(self, session: Session, message: str) -> str:
        """Mock processing for testing without OpenCode ACP.

        Returns a valid JSON response based on the agent's role.

        Args:
            session: The active session
            message: The user message

        Returns:
            Mock JSON output
        """

        role = session.role

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
            status="healthy",
            model=self.config.model,
            gpu_mem="0%",
        )

    def run(self) -> None:
        """Start the FastAPI server with uvicorn."""

        import uvicorn

        uvicorn.run(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level="info",
        )
