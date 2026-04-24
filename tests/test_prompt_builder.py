"""Unit tests for PromptBuilder and ResponseParser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from speedster.config import (
    AgentConfig,
    EventLogConfig,
    ModelConfig,
    RolesConfig,
    RoleConfig,
    StorageConfig,
)
from speedster.models import StepResult
from speedster.prompt_builder import PromptBuilder
from speedster.response_parser import ResponseParser
from speedster.task_manager import Task


@pytest.fixture
def prompt_builder(tmp_path: Path) -> PromptBuilder:
    return PromptBuilder(
        AgentConfig(
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
                event_log=EventLogConfig(path=tmp_path / "events.csv"),
                task_dir=tmp_path / "tasks",
            ),
        )
    )


@pytest.fixture
def task(tmp_path: Path) -> Task:
    task_dir = tmp_path / "tasks" / "task-test"
    task_dir.mkdir(parents=True, exist_ok=True)
    return Task(
        id="task-test",
        description="Test task description",
        priority="high",
        status="pending",
        context_dir=task_dir / "context",
    )


class TestPromptBuilder:
    def test_build_em_prompt(self, prompt_builder: PromptBuilder, task: Task) -> None:
        prompt = prompt_builder.build_em(task)
        assert "EM system prompt" in prompt
        assert "task-test" in prompt
        assert "Test task description" in prompt

    def test_build_engineer_prompt(
        self, prompt_builder: PromptBuilder, task: Task
    ) -> None:
        plan = StepResult(
            role="em",
            model="vllm/em-test",
            output=json.dumps({"id": "task-test", "tasks": []}),
        )
        prompt = prompt_builder.build_engineer(task, plan, 1)
        assert "Engineer system prompt" in prompt
        assert "task-test" in prompt
        assert "QA Feedback" not in prompt

    def test_build_engineer_prompt_with_feedback(
        self, prompt_builder: PromptBuilder, task: Task
    ) -> None:
        plan = StepResult(
            role="em",
            model="vllm/em-test",
            output=json.dumps({"id": "task-test", "tasks": []}),
        )
        prompt = prompt_builder.build_engineer(
            task, plan, 2, qa_feedback=["Missing error handling"]
        )
        assert "QA Feedback" in prompt
        assert "Missing error handling" in prompt

    def test_build_qa_prompt(
        self, prompt_builder: PromptBuilder, task: Task
    ) -> None:
        eng_result = StepResult(
            role="engineer",
            model="vllm/engineer-test",
            output=json.dumps({"status": "implemented"}),
        )
        prompt = prompt_builder.build_qa(task, eng_result, 1)
        assert "QA system prompt" in prompt
        assert "Round 1" in prompt

    def test_build_em_context_prompt(
        self, prompt_builder: PromptBuilder, task: Task
    ) -> None:
        prompt = prompt_builder.build_em_context(
            task, requested_context=["src/config.py"]
        )
        assert "Context Requested" in prompt
        assert "src/config.py" in prompt


class TestResponseParser:
    def test_parse_valid_json(self) -> None:
        parser = ResponseParser()
        result = parser.parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_invalid_json(self) -> None:
        parser = ResponseParser()
        result = parser.parse_json("not json")
        assert result is None

    def test_parse_none(self) -> None:
        parser = ResponseParser()
        result = parser.parse_json(None)  # type: ignore[arg-type]
        assert result is None

    def test_parse_qa_approved(self) -> None:
        from speedster.agent_client import AgentResponse

        parser = ResponseParser()
        response = AgentResponse(
            session_id="test",
            output=json.dumps({
                "status": "approved",
                "rejection_reasons": [],
            }),
            tokens_used=100,
            latency_ms=50,
        )
        result = parser.parse_qa(response, "vllm/qa-test")
        assert result.approved is True
        assert result.feedback == ["All criteria met"]

    def test_parse_qa_rejected(self) -> None:
        parser = ResponseParser()
        from speedster.agent_client import AgentResponse

        response = AgentResponse(
            session_id="test",
            output=json.dumps({
                "status": "rejected",
                "rejection_reasons": ["Missing tests"],
            }),
            tokens_used=100,
            latency_ms=50,
        )
        result = parser.parse_qa(response, "vllm/qa-test")
        assert result.approved is False
        assert "Missing tests" in result.feedback
