"""Prompt builder for all agent roles."""

from __future__ import annotations

import json

from speedster.config import AgentConfig
from speedster.models import StepResult
from speedster.task_manager import Task


class PromptBuilder:
    """Builds prompts for EM, Engineer, and QA agents."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def build_em(self, task: Task) -> str:
        em_config = self.config.roles.roles.get("em")
        system_prompt = em_config.system_prompt if em_config else ""

        return (
            f"{system_prompt}\n\n"
            f"## Task\n"
            f"ID: {task.id}\n"
            f"Description: {task.description}\n"
            f"Priority: {task.priority}\n"
            f"Please produce a breakdown.json with implementation plan."
        )

    def build_em_context(
        self, task: Task, requested_context: list[str]
    ) -> str:
        em_config = self.config.roles.roles.get("em")
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

    def build_engineer(
        self,
        task: Task,
        plan: StepResult,
        round_num: int,
        qa_feedback: list[str] | None = None,
    ) -> str:
        eng_config = self.config.roles.roles.get("engineer")
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
            prompt += "## QA Feedback from Previous Round\n"
            prompt += f"{feedback_text}\n\n"
            prompt += "Please address the above feedback.\n\n"

        return prompt

    def build_qa(
        self, task: Task, engineer_result: StepResult, round_num: int
    ) -> str:
        qa_config = self.config.roles.roles.get("qa")
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
