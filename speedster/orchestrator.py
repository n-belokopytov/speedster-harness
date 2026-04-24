"""Minimal workflow orchestrator for Iteration 1 vertical slice.

Drives the EM -> Engineer -> QA loop for a single task. Uses mocks/stubs
for git until GitHandler exists in Iteration 3.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

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
    feedback: list[str] | str = ""


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
        breakdown = self._parse_output(plan.output)
        if breakdown:
            try:
                self.task_manager.save_breakdown(task_id, breakdown)
            except (TypeError, ValueError, OSError) as exc:
                logger.error("Failed to save breakdown: %s", exc)
        else:
            logger.warning("EM output was not valid JSON, skipping breakdown save")

        # Step 3: Engineer -> QA loop
        max_rounds = self.config.max_qa_rounds
        round_num = 0
        qa_feedback: list[str] | None = None

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

            # Run Engineer (round_num passed for context; incremented below for QA)
            engineer_result = await self._run_engineer(
                task, plan, round_num + 1, qa_feedback
            )

            # Handle engineer status
            eng_output = self._parse_output(engineer_result.output)
            eng_status = eng_output.get("status", "implemented") if eng_output else "implemented"

            if eng_status == "blocked":
                blocked_reason = eng_output.get("blocked_reason", "Unknown") if eng_output else "Unknown"
                self.event_log.append(
                    task_id,
                    "TaskFailed",
                    "orchestrator",
                    "",
                    f"Engineer blocked: {blocked_reason}",
                )
                logger.warning(
                    "Task %s failed: engineer blocked (%s)",
                    task_id,
                    blocked_reason,
                )
                break

            elif eng_status == "needs_context":
                requested = eng_output.get("requested_context", []) if eng_output else []
                self.event_log.append(
                    task_id,
                    "ContextRequested",
                    "engineer",
                    engineer_result.model,
                    json.dumps(requested),
                )
                logger.info(
                    "Task %s engineer needs context: %s",
                    task_id,
                    requested,
                )

                # Dispatch to EM to resolve context
                context_plan = await self._run_em_for_context(task, requested)
                if context_plan.output != plan.output:
                    plan = context_plan
                    logger.info("Task %s plan updated with new context", task_id)

                # Re-dispatch to engineer in next iteration
                continue

            round_num += 1

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
                json.dumps(qa_result.feedback)
                if isinstance(qa_result.feedback, list)
                else str(qa_result.feedback),
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

            # Capture QA feedback for next engineer round
            qa_feedback = (
                qa_result.feedback
                if isinstance(qa_result.feedback, list)
                else [qa_result.feedback]
            )

            logger.info(
                "Task %s QA round %d failed, re-dispatching to Engineer",
                task_id,
                round_num,
            )

    async def _run_with_retry(
        self,
        url: str,
        prompt: str,
        validate_fn: Callable[[str], Any],
        max_retries: int = 1,
    ) -> AgentResponse:
        """Call an agent with validation and retry on ValidationError.

        Args:
            url: Agent container URL
            prompt: Prompt to send
            validate_fn: Validator function that raises ValidationError on failure
            max_retries: Number of retry attempts after initial failure

        Returns:
            Validated AgentResponse
        """

        try:
            response = await self.agent_client.work(url, prompt)
            validate_fn(response.output)
            return response

        except ValidationError as exc:
            if max_retries <= 0:
                raise

            logger.warning("Output validation failed, retrying: %s", exc)
            retry_prompt = f"{prompt}\n\nPrevious validation error: {exc}"
            response = await self.agent_client.work(url, retry_prompt)
            validate_fn(response.output)
            return response

    async def _run_em(self, task: Task) -> StepResult:
        """Run the EM agent for planning."""

        em_config = self.config.roles.get("em")
        model_name = em_config.model.model if em_config else "vllm/em-default"

        prompt = self._build_em_prompt(task)
        em_url = self.config.em_url

        response = await self._run_with_retry(
            em_url,
            prompt,
            self.validator.validate_em_breakdown,
        )

        return StepResult(
            role="em",
            model=model_name,
            output=response.output,
            tokens_used=response.tokens_used,
            latency_ms=response.latency_ms,
        )

    async def _run_em_for_context(
        self, task: Task, requested_context: list[str]
    ) -> StepResult:
        """Run the EM agent to resolve a context request from the engineer."""

        em_config = self.config.roles.get("em")
        model_name = em_config.model.model if em_config else "vllm/em-default"

        prompt = self._build_em_context_prompt(task, requested_context)
        em_url = self.config.em_url

        response = await self._run_with_retry(
            em_url,
            prompt,
            self.validator.validate_em_breakdown,
        )

        return StepResult(
            role="em",
            model=model_name,
            output=response.output,
            tokens_used=response.tokens_used,
            latency_ms=response.latency_ms,
        )

    async def _run_engineer(
        self,
        task: Task,
        plan: StepResult,
        round_num: int,
        qa_feedback: list[str] | None = None,
    ) -> StepResult:
        """Run the Engineer agent for implementation."""

        eng_config = self.config.roles.get("engineer")
        model_name = eng_config.model.model if eng_config else "vllm/engineer-default"

        prompt = self._build_engineer_prompt(task, plan, round_num, qa_feedback)
        eng_url = self.config.eng_url

        response = await self._run_with_retry(
            eng_url,
            prompt,
            self.validator.validate_engineer_output,
        )

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
        """Run the QA agent for review."""

        qa_config = self.config.roles.get("qa")
        model_name = qa_config.model.model if qa_config else "vllm/qa-default"

        prompt = self._build_qa_prompt(task, engineer_result, round_num)
        qa_url = self.config.qa_url

        response = await self._run_with_retry(
            qa_url,
            prompt,
            self.validator.validate_qa_output,
        )

        return self._parse_qa_result(response, model_name)

    def _parse_qa_result(
        self, response: AgentResponse, model_name: str
    ) -> StepResult:
        """Parse QA agent response into StepResult with approval status."""

        qa_output = self._parse_output(response.output)
        if not isinstance(qa_output, dict):
            qa_output = {}

        approved = qa_output.get("status") == "approved"
        rejection_reasons = qa_output.get("rejection_reasons", ["All criteria met"])

        feedback = (
            rejection_reasons
            if isinstance(rejection_reasons, list)
            else [str(rejection_reasons)]
        ) if not approved else ["All criteria met"]

        return StepResult(
            role="qa",
            model=model_name,
            output=response.output,
            tokens_used=response.tokens_used,
            latency_ms=response.latency_ms,
            approved=approved,
            feedback=feedback,
        )

    def _parse_output(self, output: str) -> dict[str, Any] | None:
        """Parse a JSON string output into a dict."""

        try:
            return json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None

    def _build_em_prompt(self, task: Task) -> str:
        """Build the EM prompt for a task."""

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

    def _build_em_context_prompt(
        self, task: Task, requested_context: list[str]
    ) -> str:
        """Build the EM prompt to resolve a context request."""

        em_config = self.config.roles.get("em")
        system_prompt = em_config.system_prompt if em_config else ""

        return (
            f"{system_prompt}\n\n"
            f"## Task\n"
            f"ID: {task.id}\n"
            f"Description: {task.description}\n"
            f"Priority: {task.priority}\n\n"
            f"## Context Requested by Engineer\n"
            f"{json.dumps(requested_context, indent=2)}\n\n"
            f"Please update the breakdown with the requested context information."
        )

    def _build_engineer_prompt(
        self,
        task: Task,
        plan: StepResult,
        round_num: int,
        qa_feedback: list[str] | None = None,
    ) -> str:
        """Build the Engineer prompt for implementation."""

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

        if round_num > 1 and qa_feedback:
            feedback_text = "\n".join(f"- {item}" for item in qa_feedback)
            prompt += f"## QA Feedback from Previous Round\n"
            prompt += f"{feedback_text}\n\n"
            prompt += "Please address the above feedback.\n\n"

        return prompt

    def _build_qa_prompt(
        self, task: Task, engineer_result: StepResult, round_num: int
    ) -> str:
        """Build the QA prompt for review."""

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
