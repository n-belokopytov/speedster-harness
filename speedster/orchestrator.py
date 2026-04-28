"""Minimal workflow orchestrator for Iteration 1 vertical slice.

Drives the EM -> Engineer -> QA loop for a single task with git
integration for branch management and merge tracking.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from speedster.agent_client import AgentClient, AgentResponse
from speedster.config import AgentConfig, default_config
from speedster.event_log import EventLog
from speedster.events import EventType
from speedster.git_handler import GitHandler
from speedster.interfaces import AgentGateway, EventStore
from speedster.models import StepResult
from speedster.output_validator import OutputValidator, ValidationError
from speedster.prompt_builder import PromptBuilder
from speedster.response_parser import ResponseParser
from speedster.task_manager import TaskManager, Task

logger = logging.getLogger(__name__)


class Orchestrator:
    """Workflow state machine for EM -> Engineer -> QA loop.

    Iteration 3: Includes git integration for branch-per-task workflow
    with merge tracking and diff retrieval.
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        event_store: EventStore | None = None,
        agent_gateway: AgentGateway | None = None,
        validator: OutputValidator | None = None,
        task_manager: TaskManager | None = None,
        git_handler: GitHandler | None = None,
    ):
        self.config = config or default_config()
        self.event_log: EventStore = event_store or EventLog(self.config.event_log.path)
        self.agent_gateway: AgentGateway = agent_gateway or AgentClient()
        self.task_manager = task_manager or TaskManager(self.config.task_dir)
        self.validator = validator or OutputValidator()
        self.prompt_builder = PromptBuilder(self.config)
        self.response_parser = ResponseParser()
        self.git_handler = git_handler
        self._owns_gateway = agent_gateway is None

    async def __aenter__(self) -> Orchestrator:
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._owns_gateway:
            await self.agent_gateway.close()
        if self.git_handler:
            self.git_handler.cleanup()

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

    async def resume_from_step(
        self, task: Task, step: str, breakdown: dict[str, Any] | None = None
    ) -> None:
        """Resume a task from a specific step (engineer or qa).

        Args:
            task: The task to resume
            step: The step to resume from: "em", "engineer", or "qa"
            breakdown: Previously saved EM breakdown (for engineer/qa resume)
        """

        task_id = task.id
        logger.info("Resuming task %s from step: %s", task_id, step)

        if step == "em":
            await self.process_task(task)
            return

        if breakdown is None:
            logger.warning("No breakdown available for resume, starting from EM")
            await self.process_task(task)
            return

        if step == "engineer":
            plan = StepResult(
                role="em",
                model="",
                output=json.dumps(breakdown),
            )
            await self._run_engineer_qa_loop(task_id, task, plan)

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
            EventType.TASK_CREATED,
            "orchestrator",
            "",
            f"Task accepted: {task.description}",
        )

        # Step 2: Run EM planning
        plan = await self._run_em(task)
        self.event_log.append(
            task_id,
            EventType.PLANNING_COMPLETED,
            "em",
            plan.model,
            "Plan produced",
        )

        # Save breakdown to task directory
        breakdown = self.response_parser.parse_json(plan.output)
        if breakdown:
            try:
                self.task_manager.save_breakdown(task_id, breakdown)
            except (TypeError, ValueError, OSError) as exc:
                logger.error("Failed to save breakdown: %s", exc)
        else:
            logger.warning("EM output was not valid JSON, skipping breakdown save")

        # Step 3: Engineer -> QA loop
        await self._run_engineer_qa_loop(task_id, task, plan)

    async def _run_engineer_qa_loop(
        self,
        task_id: str,
        task: Task,
        plan: StepResult,
    ) -> None:
        """Run the Engineer -> QA loop with retry and context resolution.

        Args:
            task_id: The task identifier
            task: The task being processed
            plan: The EM plan (may be updated during context resolution)
        """

        max_rounds = self.config.max_qa_rounds
        round_num = 0
        qa_feedback: list[str] | None = None

        current_plan = plan

        while True:
            if max_rounds is not None and round_num >= max_rounds:
                self.event_log.append(
                    task_id,
                    EventType.TASK_FAILED,
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

            engineer_result = await self._run_engineer(
                task, current_plan, round_num + 1, qa_feedback
            )
            eng_output = self.response_parser.parse_json(engineer_result.output)
            eng_status = (
                eng_output.get("status", "implemented")
                if eng_output
                else "implemented"
            )

            if eng_status == "blocked":
                blocked_reason = (
                    eng_output.get("blocked_reason", "Unknown")
                    if eng_output
                    else "Unknown"
                )
                self.event_log.append(
                    task_id,
                    EventType.TASK_FAILED,
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
                requested = (
                    eng_output.get("requested_context", [])
                    if eng_output
                    else []
                )
                self.event_log.append(
                    task_id,
                    EventType.CONTEXT_REQUESTED,
                    "engineer",
                    engineer_result.model,
                    json.dumps(requested),
                )
                logger.info(
                    "Task %s engineer needs context: %s",
                    task_id,
                    requested,
                )

                context_plan = await self._run_em_for_context(task, requested)
                if context_plan.output != current_plan.output:
                    current_plan = context_plan
                    logger.info("Task %s plan updated with new context", task_id)

                continue

            round_num += 1

            branch = engineer_result.branch or ""
            commit_sha = engineer_result.commit_sha or ""

            # Record branch/commit with git handler if available
            if self.git_handler:
                self.git_handler.record_implementation(
                    task_id, branch, commit_sha
                )

            impl_message = f"round={round_num}"
            if branch:
                impl_message += f", branch={branch}"
            if commit_sha:
                impl_message += f", commit={commit_sha}"

            self.event_log.append(
                task_id,
                EventType.IMPLEMENTATION_COMPLETED,
                "engineer",
                engineer_result.model,
                impl_message,
            )

            qa_result = await self._run_qa(task, engineer_result, round_num)
            self.event_log.append(
                task_id,
                EventType.REVIEW_PASSED
                if qa_result.approved
                else EventType.REVIEW_FAILED,
                "qa",
                qa_result.model,
                json.dumps(qa_result.feedback),
            )

            if qa_result.approved:
                merge_sha = ""
                if self.git_handler:
                    try:
                        merge_sha = self.git_handler.merge_to_main(
                            task_id,
                            merge_message=f"Merge task {task_id} (approved by QA)",
                        )
                        logger.info(
                            "Merged task %s into %s: %s",
                            task_id,
                            self.config.repo_default_branch or "main",
                            merge_sha[:7],
                        )
                    except Exception as merge_exc:
                        logger.warning(
                            "Failed to merge task %s: %s",
                            task_id,
                            merge_exc,
                        )

                completed_message = "Terminal state reached"
                if merge_sha:
                    completed_message += f", merged={merge_sha[:7]}"

                self.event_log.append(
                    task_id,
                    EventType.TASK_COMPLETED,
                    "orchestrator",
                    "",
                    completed_message,
                )
                logger.info("Task %s completed after %d round(s)", task_id, round_num)
                break

            qa_feedback = qa_result.feedback

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

        for attempt in range(1, max_retries + 2):
            response = await self.agent_gateway.work(url, prompt)
            try:
                validate_fn(response.output)
                return response
            except ValidationError as exc:
                if attempt > max_retries:
                    raise
                logger.warning(
                    "Output validation failed (attempt %d/%d), retrying: %s",
                    attempt,
                    max_retries + 1,
                    exc,
                )
                prompt = f"{prompt}\n\nPrevious validation error: {exc}"

    async def _run_em(self, task: Task) -> StepResult:
        """Run the EM agent for planning."""

        em_config = self.config.roles.roles.get("em")
        model_name = em_config.model.model if em_config else "vllm/em-default"

        prompt = self.prompt_builder.build_em(task)
        return await self._run_em_with_prompt(prompt)

    async def _run_em_for_context(
        self, task: Task, requested_context: list[str]
    ) -> StepResult:
        """Run the EM agent to resolve a context request from the engineer."""

        prompt = self.prompt_builder.build_em_context(task, requested_context)
        return await self._run_em_with_prompt(prompt)

    async def _run_em_with_prompt(self, prompt: str) -> StepResult:
        """Run the EM agent with a given prompt."""

        em_config = self.config.roles.roles.get("em")
        model_name = em_config.model.model if em_config else "vllm/em-default"

        response = await self._run_with_retry(
            self.config.em_url,
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

        eng_config = self.config.roles.roles.get("engineer")
        model_name = eng_config.model.model if eng_config else "vllm/engineer-default"

        prompt = self.prompt_builder.build_engineer(
            task, plan, round_num, qa_feedback
        )
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

        qa_config = self.config.roles.roles.get("qa")
        model_name = qa_config.model.model if qa_config else "vllm/qa-default"

        prompt = self.prompt_builder.build_qa(task, engineer_result, round_num)
        qa_url = self.config.qa_url

        response = await self._run_with_retry(
            qa_url,
            prompt,
            self.validator.validate_qa_output,
        )

        return self.response_parser.parse_qa(response, model_name)
