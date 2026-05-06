"""Response parser for agent outputs."""

from __future__ import annotations

import json
from typing import Any

from speedster.agent_client import AgentResponse
from speedster.models import StepResult


class ResponseParser:
    """Parses agent JSON responses into structured results."""

    def parse_json(self, output: str) -> dict[str, Any] | None:
        try:
            return json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None

    def parse_qa(self, response: AgentResponse) -> StepResult:
        qa_output = self.parse_json(response.output)
        if not isinstance(qa_output, dict):
            qa_output = {}

        approved = qa_output.get("status") == "approved"
        rejection_reasons = qa_output.get(
            "rejection_reasons", ["All criteria met"]
        )

        feedback = (
            rejection_reasons
            if isinstance(rejection_reasons, list)
            else [str(rejection_reasons)]
        ) if not approved else ["All criteria met"]

        return StepResult(
            role="qa",
            model=response.model,
            output=response.output,
            tokens_used=response.tokens_used,
            latency_ms=response.latency_ms,
            approved=approved,
            feedback=feedback,
        )
