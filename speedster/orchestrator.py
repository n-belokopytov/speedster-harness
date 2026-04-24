"""Minimal workflow orchestrator for Iteration 1 vertical slice.

Drives the EM -> Engineer -> QA loop for a single task. Uses mocks/stubs
for git until GitHandler exists in Iteration 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from speedster.agent_client import AgentClient, AgentResponse
from speedster.config import AgentConfig, default_config
from speedster.event_log import EventLog
from speedster.output_validator import OutputValidator, ValidationError
from speedster.task_manager import TaskManager, Task

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result from running a single agent step."""

    role: str
    model: str
    output: str
    tokens_used: int = 0
    latency_ms: int = 0
    branch: str = ""
    commit_sha: str = ""
    approved: bool = False
    feedback: str = ""


class Orchestrator:
    """Workflow state machine for EM -> Engineer -> QA loop.

    Iteration 1: Single task vertical slice with minimal state management.
    """

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or default_config()
        self.event_log = EventLog(self.config.event_log.path)
        self.agent_client = AgentClient()
        self.task_manager = TaskManager(self.config.task_dir, self.event_log)
        self.validator = OutputValidator()

    async def run(self, task_id: str | None = None) -> None:
        """Run the orchestrator loop.

        If task_id is provided, process that specific task.
        Otherwise, find the first pending task.
        """

        if task_id:
            task = self.task_manager.load_task(task_id)
            await self.process_task(task)
        else:
            tasks = self.task_manager.list_tasks()
            for task in tasks:
                if task.status == "pending":
                    await self.process_task(task)
                    break

    async def process_task(self, task: Task) -> None:
        """Process a single task through the EM -> Engineer -> QA loop.

        Args:
            task: The task to process
        """

        task_id = task.id
        logger.info("Processing task: %s", task_id)

        # Step 1: Record task creation
        self.event_log.append(
            task_id,
            "TaskCreated",
            "orchestrator",
            "",
            f"Task accepted: {task.description}",
        )

        # Step 2: Run EM planning
        plan = await self._run_em(task)
        self.event_log.append(
            task_id,
            "PlanningCompleted",
            "em",
            plan.model,
            "Plan produced",
        )

        # Save breakdown to task directory
        try:
            import json

            breakdown = json.loads(plan.output)
            self.task_manager.save_breakdown(task_id, breakdown)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to save breakdown: %s", exc)

        # Step 3: Engineer -> QA loop
        max_rounds = self.config.max_qa_rounds
        round_num = 0

        while True:
            if max_rounds is not None and round_num >= max_rounds:
                self.event_log.append(
                    task_id,
                    "TaskFailed",
                    "orchestrator",
                    "",
                    "Max QA rounds exceeded",
                )
                logger.warning(
                    "Task %s failed: max QA rounds (%d) exceeded",
                    task_id,
                    max_rounds,
                )
                break

            round_num += 1

            # Run Engineer
            engineer_result = await self._run_engineer(task, plan, round_num)
            self.event_log.append(
                task_id,
                "ImplementationCompleted",
                "engineer",
                engineer_result.model,
                f"round={round_num}",
            )

            # Run QA
            qa_result = await self._run_qa(task, engineer_result, round_num)
            self.event_log.append(
                task_id,
                "ReviewPassed" if qa_result.approved else "ReviewFailed",
                "qa",
                qa_result.model,
                qa_result.feedback,
            )

            if qa_result.approved:
                self.event_log.append(
                    task_id,
                    "TaskCompleted",
                    "orchestrator",
                    "",
                    "Terminal state reached",
                )
                logger.info("Task %s completed after %d round(s)", task_id, round_num)
                break

            logger.info(
                "Task %s QA round %d failed, re-dispatching to Engineer",
                task_id,
                round_num,
            )

    async def _run_em(self, task: Task) -> StepResult:
        """Run the EM agent for planning.

        Args:
            task: The task to plan

        Returns:
            StepResult with EM output
        """

        em_config = self.config.roles.get("em")
        model_name = em_config.model.model if em_config else "vllm/em-default"

        # Build prompt from task
        prompt = self._build_em_prompt(task)

        # Get EM agent URL from config or use default
        em_url = getattr(self.config, "em_url", "http://localhost:8081")

        try:
            response = self.agent_client.work(em_url, prompt)

            # Validate EM output
            self.validator.validate_em_breakdown(response.output)

            return StepResult(
                role="em",
                model=model_name,
                output=response.output,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
            )

        except ValidationError as exc:
            logger.warning("EM output validation failed, retrying: %s", exc)
            retry_prompt = f"{prompt}\n\nPrevious validation error: {exc}"
            response = self.agent_client.work(em_url, retry_prompt)

            self.validator.validate_em_breakdown(response.output)

            return StepResult(
                role="em",
                model=model_name,
                output=response.output,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
            )

    async def _run_engineer(
        self, task: Task, plan: StepResult, round_num: int
    ) -> StepResult:
        """Run the Engineer agent for implementation.

        Args:
            task: The task to implement
            plan: The EM plan output
            round_num: Current QA round number

        Returns:
            StepResult with Engineer output
        """

        eng_config = self.config.roles.get("engineer")
        model_name = eng_config.model.model if eng_config else "vllm/engineer-default"

        prompt = self._build_engineer_prompt(task, plan, round_num)

        eng_url = getattr(self.config, "eng_url", "http://localhost:8082")

        try:
            response = self.agent_client.work(eng_url, prompt)
            self.validator.validate_engineer_output(response.output)

            return StepResult(
                role="engineer",
                model=model_name,
                output=response.output,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
                branch=f"speedster/{task.id}",
            )

        except ValidationError as exc:
            logger.warning(
                "Engineer output validation failed, retrying: %s", exc
            )
            retry_prompt = f"{prompt}\n\nPrevious validation error: {exc}"
            response = self.agent_client.work(eng_url, retry_prompt)

            self.validator.validate_engineer_output(response.output)

            return StepResult(
                role="engineer",
                model=model_name,
                output=response.output,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
                branch=f"speedster/{task.id}",
            )

    async def _run_qa(
        self, task: Task, engineer_result: StepResult, round_num: int
    ) -> StepResult:
        """Run the QA agent for review.

        Args:
            task: The task to review
            engineer_result: The engineer's output
            round_num: Current QA round number

        Returns:
            StepResult with QA output and approval status
        """

        qa_config = self.config.roles.get("qa")
        model_name = qa_config.model.model if qa_config else "vllm/qa-default"

        prompt = self._build_qa_prompt(task, engineer_result, round_num)

        qa_url = getattr(self.config, "qa_url", "http://localhost:8083")

        try:
            response = self.agent_client.work(qa_url, prompt)
            qa_output = self.validator.validate_qa_output(response.output)

            # Determine approval status
            if isinstance(qa_output, str):
                import json

                qa_output = json.loads(qa_output)

            approved = qa_output.get("status") == "approved"
            rejection_reasons = qa_output.get("rejection_reasons", ["All criteria met"])

            if not approved:
                feedback = (
                    ", ".join(rejection_reasons)
                    if isinstance(rejection_reasons, list)
                    else str(rejection_reasons)
                )
            else:
                feedback = "All criteria met"

            return StepResult(
                role="qa",
                model=model_name,
                output=response.output,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
                approved=approved,
                feedback=feedback,
            )

        except ValidationError as exc:
            logger.warning("QA output validation failed, retrying: %s", exc)
            retry_prompt = f"{prompt}\n\nPrevious validation error: {exc}"
            response = self.agent_client.work(qa_url, retry_prompt)

            qa_output = self.validator.validate_qa_output(response.output)

            if isinstance(qa_output, str):
                import json

                qa_output = json.loads(qa_output)

            approved = qa_output.get("status") == "approved"
            rejection_reasons = qa_output.get("rejection_reasons", ["All criteria met"])

            if not approved:
                feedback = (
                    ", ".join(rejection_reasons)
                    if isinstance(rejection_reasons, list)
                    else str(rejection_reasons)
                )
            else:
                feedback = "All criteria met"

            return StepResult(
                role="qa",
                model=model_name,
                output=response.output,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
                approved=approved,
                feedback=feedback,
            )

    def _build_em_prompt(self, task: Task) -> str:
        """Build the EM prompt for a task.

        Args:
            task: The task to plan

        Returns:
            Prompt string for the EM agent
        """

        em_config = self.config.roles.get("em")
        system_prompt = em_config.system_prompt if em_config else ""

        return (
            f"{system_prompt}\n\n"
            f"## Task\n"
            f"ID: {task.id}\n"
            f"Description: {task.description}\n"
            f"Priority: {task.priority}\n"
            f"Please produce a breakdown.json with implementation plan."
        )

    def _build_engineer_prompt(
        self, task: Task, plan: StepResult, round_num: int
    ) -> str:
        """Build the Engineer prompt for implementation.

        Args:
            task: The task to implement
            plan: The EM plan
            round_num: Current round number

        Returns:
            Prompt string for the Engineer agent
        """

        eng_config = self.config.roles.get("engineer")
        system_prompt = eng_config.system_prompt if eng_config else ""

        prompt = (
            f"{system_prompt}\n\n"
            f"## Task\n"
            f"ID: {task.id}\n"
            f"Description: {task.description}\n\n"
            f"## Plan\n"
            f"{plan.output}\n\n"
        )

        if round_num > 1:
            prompt += f"## Previous Round ({round_num - 1}) Feedback\n"
            prompt += "Please address the QA feedback below.\n\n"

        return prompt

    def _build_qa_prompt(
        self, task: Task, engineer_result: StepResult, round_num: int
    ) -> str:
        """Build the QA prompt for review.

        Args:
            task: The task to review
            engineer_result: The engineer's output
            round_num: Current round number

        Returns:
            Prompt string for the QA agent
        """

        qa_config = self.config.roles.get("qa")
        system_prompt = qa_config.system_prompt if qa_config else ""

        return (
            f"{system_prompt}\n\n"
            f"## Task\n"
            f"ID: {task.id}\n"
            f"Description: {task.description}\n"
            f"Priority: {task.priority}\n\n"
            f"## Engineer Output (Round {round_num})\n"
            f"{engineer_result.output}\n\n"
            f"Please review and produce a QA review with findings."
        )
