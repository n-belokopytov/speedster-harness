"""Unit tests for the orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from speedster.git_handler import GitMergeResult
from speedster.config import (
    AgentConfig,
    EventLogConfig,
    ModelConfig,
    RolesConfig,
    RoleConfig,
    StorageConfig,
)
from speedster.event_log import EventLog
from speedster.models import StepResult
from speedster.orchestrator import Orchestrator
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


def make_engineer_blocked_output() -> dict:
    """Create a valid engineer output with blocked status."""

    return {
        "task_id": "task-test",
        "status": "blocked",
        "branch": "speedster/task-test",
        "files_changed": [],
        "tests_added_or_updated": [],
        "acceptance_evidence": {
            "functional": [],
            "solid": "N/A",
            "yagni_kiss": "N/A",
            "testing": "N/A",
        },
        "assumptions": [],
        "notes": "",
        "blocked_reason": "Dependency API unavailable",
        "requested_context": [],
    }


def make_engineer_needs_context_output() -> dict:
    """Create a valid engineer output with needs_context status."""

    return {
        "task_id": "task-test",
        "status": "needs_context",
        "branch": "speedster/task-test",
        "files_changed": [],
        "tests_added_or_updated": [],
        "acceptance_evidence": {
            "functional": [],
            "solid": "N/A",
            "yagni_kiss": "N/A",
            "testing": "N/A",
        },
        "assumptions": [],
        "notes": "",
        "blocked_reason": "",
        "requested_context": ["src/config.py", "README.md"],
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


def _make_async_response(output: str, tokens: int = 100, latency: int = 50) -> MagicMock:
    """Create a mock async agent response."""

    return MagicMock(
        session_id="test-session",
        output=output,
        tokens_used=tokens,
        latency_ms=latency,
    )


@pytest.fixture
def config(tmp_path: Path) -> AgentConfig:
    """Create a test configuration."""

    event_log_path = tmp_path / "state" / "events.csv"
    event_log_path.parent.mkdir(parents=True, exist_ok=True)

    return AgentConfig(
        roles=RolesConfig(
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
            }
        ),
        storage=StorageConfig(
            event_log=EventLogConfig(path=event_log_path),
            task_dir=tmp_path / "tasks",
        ),
        max_qa_rounds=3,
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
            orchestrator.agent_gateway,
            "work",
            new_callable=AsyncMock,
            side_effect=[
                _make_async_response(em_output),
                _make_async_response(engineer_output),
                _make_async_response(qa_output),
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
            orchestrator.agent_gateway,
            "work",
            new_callable=AsyncMock,
            side_effect=[
                _make_async_response(em_output),
                _make_async_response(engineer_output),
                _make_async_response(qa_reject),
                _make_async_response(engineer_output),
                _make_async_response(qa_approve),
            ],
        ):
            await orchestrator.process_task(task)

        events = list(orchestrator.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert event_types.count("ImplementationCompleted") == 2
        assert "ReviewFailed" in event_types
        assert "ReviewPassed" in event_types
        assert "TaskCompleted" in event_types

    @pytest.mark.asyncio
    async def test_qa_feedback_passed_to_engineer(
        self, orchestrator: Orchestrator, task: Task, tmp_path: Path
    ) -> None:
        """Test that QA feedback is passed to engineer on re-dispatch."""

        em_output = json.dumps(make_valid_breakdown())
        engineer_output = json.dumps(make_valid_engineer_output())
        qa_reject = json.dumps(make_valid_qa_output("rejected", 1))
        qa_approve = json.dumps(make_valid_qa_output("approved", 2))

        work_mock = AsyncMock(
            side_effect=[
                _make_async_response(em_output),
                _make_async_response(engineer_output),
                _make_async_response(qa_reject),
                _make_async_response(engineer_output),
                _make_async_response(qa_approve),
            ]
        )

        with patch.object(orchestrator.agent_gateway, "work", work_mock):
            await orchestrator.process_task(task)

        calls = work_mock.call_args_list
        engineer_calls = [
            c for c in calls if len(c[0]) >= 1 and "8082" in c[0][0]
        ]
        assert len(engineer_calls) == 2
        second_eng_payload = engineer_calls[1][0][1]
        assert "qa_feedback" in second_eng_payload
        assert "Missing error handling" in second_eng_payload["qa_feedback"]


class TestEngineerStatuses:
    @pytest.mark.asyncio
    async def test_engineer_blocked_fails_task(
        self, orchestrator: Orchestrator, task: Task, tmp_path: Path
    ) -> None:
        """Test that a blocked engineer status fails the task."""

        em_output = json.dumps(make_valid_breakdown())
        blocked_output = json.dumps(make_engineer_blocked_output())

        with patch.object(
            orchestrator.agent_gateway,
            "work",
            new_callable=AsyncMock,
            side_effect=[
                _make_async_response(em_output),
                _make_async_response(blocked_output),
            ],
        ):
            await orchestrator.process_task(task)

        events = list(orchestrator.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert "TaskFailed" in event_types
        failed_event = next(e for e in events if e["event_type"] == "TaskFailed")
        assert "blocked" in failed_event["message"].lower()
        assert "Dependency API unavailable" in failed_event["message"]

    @pytest.mark.asyncio
    async def test_engineer_needs_context_dispatches_to_em(
        self, orchestrator: Orchestrator, task: Task, tmp_path: Path
    ) -> None:
        """Test that needs_context dispatches to EM for context resolution."""

        em_output = json.dumps(make_valid_breakdown())
        needs_context = json.dumps(make_engineer_needs_context_output())
        engineer_output = json.dumps(make_valid_engineer_output())
        qa_output = json.dumps(make_valid_qa_output("approved"))

        with patch.object(
            orchestrator.agent_gateway,
            "work",
            new_callable=AsyncMock,
            side_effect=[
                _make_async_response(em_output),
                _make_async_response(needs_context),
                _make_async_response(em_output),
                _make_async_response(engineer_output),
                _make_async_response(qa_output),
            ],
        ):
            await orchestrator.process_task(task)

        events = list(orchestrator.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert "ContextRequested" in event_types
        assert "TaskCompleted" in event_types

    @pytest.mark.asyncio
    async def test_needs_context_does_not_consume_qa_round(
        self, config: AgentConfig, task: Task, tmp_path: Path
    ) -> None:
        """Test that needs_context re-dispatches don't count against max_qa_rounds."""

        config.max_qa_rounds = 1
        orchestrator = Orchestrator(config)

        em_output = json.dumps(make_valid_breakdown())
        needs_context = json.dumps(make_engineer_needs_context_output())
        engineer_output = json.dumps(make_valid_engineer_output())
        qa_output = json.dumps(make_valid_qa_output("approved"))

        with patch.object(
            orchestrator.agent_gateway,
            "work",
            new_callable=AsyncMock,
            side_effect=[
                _make_async_response(em_output),
                _make_async_response(needs_context),
                _make_async_response(em_output),
                _make_async_response(engineer_output),
                _make_async_response(qa_output),
            ],
        ):
            await orchestrator.process_task(task)

        events = list(orchestrator.event_log.replay())
        event_types = [e["event_type"] for e in events]

        assert "ContextRequested" in event_types
        assert "TaskCompleted" in event_types
        assert "TaskFailed" not in event_types


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
            orchestrator.agent_gateway,
            "work",
            new_callable=AsyncMock,
            side_effect=[
                _make_async_response(em_output),
                _make_async_response(engineer_output),
                _make_async_response(qa_reject),
                _make_async_response(engineer_output),
                _make_async_response(qa_reject),
                _make_async_response(engineer_output),
                _make_async_response(qa_reject),
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


class TestStepResult:
    def test_feedback_is_list(self) -> None:
        result = StepResult(
            role="qa",
            model="test",
            output="",
            feedback=["reason 1", "reason 2"],
        )
        assert isinstance(result.feedback, list)
        assert result.feedback == ["reason 1", "reason 2"]

    def test_feedback_default(self) -> None:
        result = StepResult(
            role="qa",
            model="test",
            output="",
        )
        assert result.feedback == ["All criteria met"]

    def test_feedback_is_mutable_default(self) -> None:
        r1 = StepResult(role="qa", model="test", output="")
        r2 = StepResult(role="qa", model="test", output="")
        r1.feedback.append("modified")
        assert r1.feedback != r2.feedback


class TestParseOutput:
    def test_parse_valid_json(self, orchestrator: Orchestrator) -> None:
        result = orchestrator.response_parser.parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_invalid_json(self, orchestrator: Orchestrator) -> None:
        result = orchestrator.response_parser.parse_json("not json")
        assert result is None

    def test_parse_none(self, orchestrator: Orchestrator) -> None:
        result = orchestrator.response_parser.parse_json(None)  # type: ignore[arg-type]
        assert result is None


class TestOrchestratorGitIntegration:
    """Tests for orchestrator git handler integration."""

    @pytest.fixture
    def mock_git_handler(self) -> MagicMock:
        """Create a mock GitHandler."""

        handler = MagicMock()
        handler.record_implementation = MagicMock()
        handler.merge_to_main = AsyncMock(return_value=GitMergeResult(sha="abcdef1234567890"))
        handler.cleanup = MagicMock()
        return handler

    @pytest.mark.asyncio
    async def test_implementation_event_includes_branch(
        self, mock_git_handler: MagicMock, tmp_path: Path
    ) -> None:
        """ImplementationCompleted event should include branch and commit."""

        event_log_path = tmp_path / "events.csv"
        task_dir = tmp_path / "tasks"
        task_git_dir = task_dir / "task-git"
        task_git_dir.mkdir(parents=True)
        (task_git_dir / "task.json").write_text(
            json.dumps({
                "id": "task-git",
                "description": "Git integration test",
                "priority": "high",
                "status": "pending",
            })
        )

        config = AgentConfig(
            roles=RolesConfig(
                roles={
                    "em": RoleConfig(
                        model=ModelConfig(model="vllm/em-test"),
                        system_prompt="EM prompt",
                    ),
                    "engineer": RoleConfig(
                        model=ModelConfig(model="vllm/engineer-test"),
                        system_prompt="Engineer prompt",
                    ),
                    "qa": RoleConfig(
                        model=ModelConfig(model="vllm/qa-test"),
                        system_prompt="QA prompt",
                    ),
                }
            ),
            storage=StorageConfig(
                event_log=EventLogConfig(path=event_log_path),
                task_dir=task_dir,
            ),
            max_qa_rounds=3,
        )

        event_log = EventLog(event_log_path)

        # Build valid responses for EM, Engineer, QA
        breakdown = make_valid_breakdown()
        breakdown["id"] = "task-git"
        eng_output = make_valid_engineer_output()
        eng_output["task_id"] = "task-git"
        eng_output["branch"] = "speedster/task-git"
        qa_output = make_valid_qa_output("approved")
        qa_output["task_id"] = "task-git"

        mock_gateway = AsyncMock()
        mock_gateway.work = AsyncMock(
            side_effect=[
                MagicMock(output=json.dumps(breakdown), tokens_used=100, latency_ms=50),
                MagicMock(output=json.dumps(eng_output), tokens_used=100, latency_ms=50),
                MagicMock(output=json.dumps(qa_output), tokens_used=100, latency_ms=50),
            ]
        )
        mock_gateway.close = AsyncMock()

        orch = Orchestrator(
            config=config,
            event_store=event_log,
            agent_gateway=mock_gateway,
            git_handler=mock_git_handler,
        )

        task = orch.task_manager.load_task("task-git")
        await orch.process_task(task)

        # Verify git handler was called
        mock_git_handler.record_implementation.assert_called_once()
        call_args = mock_git_handler.record_implementation.call_args
        assert call_args[0][0] == "task-git"
        assert call_args[0][1] == "speedster/task-git"

        # Verify merge was called on TaskCompleted
        mock_git_handler.merge_to_main.assert_called_once()

        # Verify events contain branch info
        events = list(event_log.replay())
        impl_event = [e for e in events if e["event_type"] == "ImplementationCompleted"][0]
        assert "branch=speedster/task-git" in impl_event["message"]
