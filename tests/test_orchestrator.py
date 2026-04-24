"""Unit tests for the orchestrator."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from speedster.config import AgentConfig, EventLogConfig, ModelConfig, RoleConfig
from speedster.event_log import EventLog
from speedster.orchestrator import Orchestrator, StepResult
from speedster.task_manager import Task


def make_valid_breakdown() -> dict:
    """Create a valid EM breakdown that passes schema validation."""

    return {
        "id": "task-test",
        "description": "Add user authentication with JWT",
        "acceptance_criteria": {
            "functional": ["Login endpoint returns 200 on valid credentials"],
            "solid": "The implementation adheres to SOLID principles by separating concerns.",
            "yagni_kiss": "The implementation adheres to YAGNI and KISS by keeping it simple.",
            "testing": "Well-designed unit tests cover the behavior, with minimum unit test coverage of 80%+ for touched modules.",
        },
        "context_files": ["src/auth.py"],
        "context_rationale": "Auth module needs changes",
        "depends_on": [],
        "estimated_context_tokens": 1000,
        "estimated_work_tokens": 5000,
        "complexity_level": "simple",
        "target_model_class": "mid-size-25B",
        "status": "pending",
        "qa_rounds": 0,
        "feedback": None,
        "tasks": [],
    }


def make_valid_engineer_output() -> dict:
    """Create a valid engineer output."""

    return {
        "task_id": "task-test",
        "status": "implemented",
        "branch": "speedster/task-test",
        "files_changed": ["src/auth.py"],
        "tests_added_or_updated": ["tests/test_auth.py"],
        "acceptance_evidence": {
            "functional": [
                {"criterion": "Login returns 200", "evidence": "Test passes"}
            ],
            "solid": "Separation of concerns maintained",
            "yagni_kiss": "Simple solution implemented",
            "testing": "Unit tests added for auth module",
        },
        "assumptions": [],
        "notes": "",
        "blocked_reason": "",
        "requested_context": [],
    }


def make_valid_qa_output(status: str = "approved", round_num: int = 1) -> dict:
    """Create a valid QA output."""

    if status == "approved":
        return {
            "task_id": "task-test",
            "status": "approved",
            "branch": "speedster/task-test",
            "commit": "abc123def456",
            "round": round_num,
            "findings": {
                "functional": [
                    {
                        "criterion": "Login returns 200",
                        "verdict": "met",
                        "evidence": "Test passes with valid credentials",
                    }
                ],
                "solid": {"verdict": "met", "evidence": "Good separation"},
                "yagni_kiss": {"verdict": "met", "evidence": "Simple solution"},
                "testing": {"verdict": "met", "evidence": "Unit tests added"},
            },
            "rejection_reasons": [],
            "notes": "",
        }
    else:
        return {
            "task_id": "task-test",
            "status": "rejected",
            "branch": "speedster/task-test",
            "commit": "abc123def456",
            "round": round_num,
            "findings": {
                "functional": [
                    {
                        "criterion": "Login returns 200",
                        "verdict": "unmet",
                        "evidence": "Missing error handling",
                    }
                ],
                "solid": {"verdict": "met", "evidence": "Good separation"},
                "yagni_kiss": {"verdict": "met", "evidence": "Simple solution"},
                "testing": {"verdict": "met", "evidence": "Unit tests added"},
            },
            "rejection_reasons": ["Missing error handling"],
            "notes": "",
        }


@pytest.fixture
def config(tmp_path: Path) -> AgentConfig:
    """Create a test configuration."""

    event_log_path = tmp_path / "state" / "events.csv"
    event_log_path.parent.mkdir(parents=True, exist_ok=True)

    return AgentConfig(
        roles={
            "em": RoleConfig(
                model=ModelConfig(model="vllm/em-test"),
                system_prompt="EM system prompt",
            ),
            "engineer": RoleConfig(
                model=ModelConfig(model="vllm/engineer-test"),
                system_prompt="Engineer system prompt",
            ),
            "qa": RoleConfig(
                model=ModelConfig(model="vllm/qa-test"),
                system_prompt="QA system prompt",
            ),
        },
        event_log=EventLogConfig(path=event_log_path),
        max_qa_rounds=3,
        task_dir=tmp_path / "tasks",
    )


@pytest.fixture
def task(tmp_path: Path) -> Task:
    """Create a test task."""

    task_dir = tmp_path / "tasks" / "task-test"
    task_dir.mkdir(parents=True, exist_ok=True)

    return Task(
        id="task-test",
        description="Add user authentication with JWT",
        priority="high",
        status="pending",
        context_dir=task_dir / "context",
    )


@pytest.fixture
def orchestrator(config: AgentConfig) -> Orchestrator:
    """Create an orchestrator instance."""

    return Orchestrator(config)


class TestOrchestratorInit:
    def test_creates_event_log(self, orchestrator: Orchestrator) -> None:
        assert orchestrator.event_log is not None
        assert orchestrator.event_log.path.exists()

    def test_has_validator(self, orchestrator: Orchestrator) -> None:
        assert orchestrator.validator is not None

    def test_has_task_manager(self, orchestrator: Orchestrator) -> None:
        assert orchestrator.task_manager is not None


class TestBuildPrompts:
    def test_build_em_prompt(self, orchestrator: Orchestrator, task: Task) -> None:
        prompt = orchestrator._build_em_prompt(task)
        assert "EM system prompt" in prompt
        assert "task-test" in prompt
        assert "Add user authentication" in prompt

    def test_build_engineer_prompt(
        self, orchestrator: Orchestrator, task: Task
    ) -> None:
        plan = StepResult(
            role="em",
            model="vllm/em-test",
            output=json.dumps(make_valid_breakdown()),
        )
        prompt = orchestrator._build_engineer_prompt(task, plan, 1)
        assert "Engineer system prompt" in prompt
        assert "task-test" in prompt

    def test_build_engineer_prompt_with_feedback(
        self, orchestrator: Orchestrator, task: Task
    ) -> None:
        plan = StepResult(
            role="em",
            model="vllm/em-test",
            output=json.dumps(make_valid_breakdown()),
        )
        prompt = orchestrator._build_engineer_prompt(task, plan, 2)
        assert "Previous Round" in prompt
        assert "QA feedback" in prompt

    def test_build_qa_prompt(
        self, orchestrator: Orchestrator, task: Task
    ) -> None:
        engineer_result = StepResult(
            role="engineer",
            model="vllm/engineer-test",
            output=json.dumps(make_valid_engineer_output()),
        )
        prompt = orchestrator._build_qa_prompt(task, engineer_result, 1)
        assert "QA system prompt" in prompt
        assert "task-test" in prompt
        assert "Round 1" in prompt


class TestProcessTask:
    @pytest.mark.asyncio
    async def test_em_to_qa_approve_path(
        self, orchestrator: Orchestrator, task: Task, tmp_path: Path
    ) -> None:
        """Test the happy path: EM -> Engineer -> QA approve."""

        em_output = json.dumps(make_valid_breakdown())
        engineer_output = json.dumps(make_valid_engineer_output())
        qa_output = json.dumps(make_valid_qa_output("approved"))

        with patch.object(
            orchestrator.agent_client,
            "work",
            side_effect=[
                MagicMock(
                    session_id="test-session",
                    output=em_output,
                    tokens_used=100,
                    latency_ms=50,
                ),
                MagicMock(
                    session_id="test-session",
                    output=engineer_output,
                    tokens_used=200,
                    latency_ms=100,
                ),
                MagicMock(
                    session_id="test-session",
                    output=qa_output,
                    tokens_used=150,
                    latency_ms=75,
                ),
            ],
        ):
            await orchestrator.process_task(task)

        events = list(orchestrator.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert "TaskCreated" in event_types
        assert "PlanningCompleted" in event_types
        assert "ImplementationCompleted" in event_types
        assert "ReviewPassed" in event_types
        assert "TaskCompleted" in event_types

    @pytest.mark.asyncio
    async def test_qa_reject_then_approve(
        self, orchestrator: Orchestrator, task: Task, tmp_path: Path
    ) -> None:
        """Test QA rejection followed by approval on retry."""

        em_output = json.dumps(make_valid_breakdown())
        engineer_output = json.dumps(make_valid_engineer_output())
        qa_reject = json.dumps(make_valid_qa_output("rejected", 1))
        qa_approve = json.dumps(make_valid_qa_output("approved", 2))

        with patch.object(
            orchestrator.agent_client,
            "work",
            side_effect=[
                MagicMock(session_id="s", output=em_output, tokens_used=100, latency_ms=50),
                MagicMock(session_id="s", output=engineer_output, tokens_used=200, latency_ms=100),
                MagicMock(session_id="s", output=qa_reject, tokens_used=150, latency_ms=75),
                MagicMock(session_id="s", output=engineer_output, tokens_used=200, latency_ms=100),
                MagicMock(session_id="s", output=qa_approve, tokens_used=150, latency_ms=75),
            ],
        ):
            await orchestrator.process_task(task)

        events = list(orchestrator.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert event_types.count("ImplementationCompleted") == 2
        assert "ReviewFailed" in event_types
        assert "ReviewPassed" in event_types
        assert "TaskCompleted" in event_types


class TestMaxQARounds:
    @pytest.mark.asyncio
    async def test_max_rounds_exceeded(
        self, config: AgentConfig, task: Task, tmp_path: Path
    ) -> None:
        """Test that max QA rounds circuit breaker works."""

        orchestrator = Orchestrator(config)

        em_output = json.dumps(make_valid_breakdown())
        engineer_output = json.dumps(make_valid_engineer_output())
        qa_reject = json.dumps(make_valid_qa_output("rejected", 1))

        # Always reject to trigger max rounds
        with patch.object(
            orchestrator.agent_client,
            "work",
            side_effect=[
                MagicMock(session_id="s", output=em_output, tokens_used=100, latency_ms=50),
                MagicMock(session_id="s", output=engineer_output, tokens_used=200, latency_ms=100),
                MagicMock(session_id="s", output=qa_reject, tokens_used=150, latency_ms=75),
                MagicMock(session_id="s", output=engineer_output, tokens_used=200, latency_ms=100),
                MagicMock(session_id="s", output=qa_reject, tokens_used=150, latency_ms=75),
                MagicMock(session_id="s", output=engineer_output, tokens_used=200, latency_ms=100),
                MagicMock(session_id="s", output=qa_reject, tokens_used=150, latency_ms=75),
            ],
        ):
            await orchestrator.process_task(task)

        events = list(orchestrator.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert "TaskFailed" in event_types
        failed_event = next(
            e for e in events if e["event_type"] == "TaskFailed"
        )
        assert "Max QA rounds exceeded" in failed_event["message"]
