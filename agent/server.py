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
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.config import AgentConfig

logger = logging.getLogger(__name__)


class WorkRequest(BaseModel):
    """Request body for /work endpoint."""

    message: str
    session_id: str | None = None


class WorkResponse(BaseModel):
    """Response from /work endpoint."""

    session_id: str
    output: str
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
        self._mock_mode = True  # Set to False when OpenCode ACP is available

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
            request: The work request with message and optional session_id

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
        session.messages.append({"role": "user", "content": request.message})

        try:
            # Process through OpenCode ACP (or mock for now)
            output = await self._process_message(session, request.message)
            latency_ms = int((time.time() - start_time) * 1000)

            return WorkResponse(
                session_id=session_id,
                output=output,
                tokens_used=len(output.split()),  # Approximate token count
                latency_ms=latency_ms,
            )

        except Exception as exc:
            logger.error("Work processing failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    async def _process_message(
        self, session: Session, message: str
    ) -> str:
        """Process a message through OpenCode ACP.

        In Iteration 1, this uses a mock response. In production,
        this would call the OpenCode ACP server with the system prompt
        and user message.

        Args:
            session: The active session
            message: The user message to process

        Returns:
            The agent's output
        """

        if self._mock_mode:
            return await self._mock_process(session, message)

        # TODO: Integrate with OpenCode ACP server
        # This would load the system prompt from prompts/, send the
        # message to the model, and return the response.
        raise NotImplementedError("OpenCode ACP integration not yet implemented")

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
            gpu_mem="0%",  # TODO: Add GPU memory reporting
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
