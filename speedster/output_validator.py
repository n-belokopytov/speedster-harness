"""Unified output validator for all agent roles.

Wraps the existing tools/ validation libraries to provide a single
interface the orchestrator can use for validating agent input/output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure tools/ is importable
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from em_breakdown import (  # noqa: E402
    BreakdownValidationError,
    validate_breakdown as _validate_em_breakdown,
)
from engineer_contract import (  # noqa: E402
    ContractValidationError as EngineerContractError,
    validate_engineer_input as _validate_engineer_input,
    validate_engineer_output as _validate_engineer_output,
)
from qa_contract import (  # noqa: E402
    ContractValidationError as QAContractError,
    validate_qa_input as _validate_qa_input,
    validate_qa_output as _validate_qa_output,
)


class ValidationError(Exception):
    """Raised when agent output fails validation."""


class OutputValidator:
    """Central validator for all agent contracts.

    Validates agent input/output payloads against their respective
    JSON schemas and structural invariants.
    """

    # Output types the orchestrator validates
    OUTPUT_TYPES = {
        "em_breakdown": "EM planning output (breakdown tree)",
        "engineer_input": "Orchestrator -> Engineer dispatch payload",
        "engineer_output": "Engineer -> Orchestrator response",
        "qa_input": "Orchestrator -> QA dispatch payload",
        "qa_output": "QA -> Orchestrator review response",
    }

    def validate(
        self,
        data: dict[str, Any] | str,
        output_type: str,
    ) -> dict[str, Any] | None:
        """Validate a payload against the appropriate schema.

        Args:
            data: JSON object (dict) or JSON string to validate
            output_type: One of the keys in OUTPUT_TYPES

        Returns:
            Parsed/validated dict on success, None on parse failure
            (signals retry needed), or raises ValidationError with
            details for structured retry.
        """

        if output_type not in self.OUTPUT_TYPES:
            raise ValidationError(f"Unknown output type: {output_type}")

        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                return None  # signals retry needed

        if not isinstance(data, dict):
            raise ValidationError("Payload must be a JSON object")

        try:
            if output_type == "em_breakdown":
                _validate_em_breakdown(data)
            elif output_type == "engineer_input":
                _validate_engineer_input(data)
            elif output_type == "engineer_output":
                _validate_engineer_output(data)
            elif output_type == "qa_input":
                _validate_qa_input(data)
            elif output_type == "qa_output":
                _validate_qa_output(data)

            return data

        except (
            BreakdownValidationError,
            EngineerContractError,
            QAContractError,
        ) as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            # Catch jsonschema.ValidationError and other unexpected errors
            raise ValidationError(str(exc)) from exc

    def validate_em_breakdown(self, data: dict[str, Any] | str) -> dict[str, Any]:
        """Validate EM breakdown output."""

        result = self.validate(data, "em_breakdown")
        if result is None:
            raise ValidationError("EM output is not valid JSON")
        return result

    def validate_engineer_input(self, data: dict[str, Any] | str) -> dict[str, Any]:
        """Validate engineer dispatch payload."""

        result = self.validate(data, "engineer_input")
        if result is None:
            raise ValidationError("Engineer input is not valid JSON")
        return result

    def validate_engineer_output(self, data: dict[str, Any] | str) -> dict[str, Any]:
        """Validate engineer response."""

        result = self.validate(data, "engineer_output")
        if result is None:
            raise ValidationError("Engineer output is not valid JSON")
        return result

    def validate_qa_input(self, data: dict[str, Any] | str) -> dict[str, Any]:
        """Validate QA dispatch payload."""

        result = self.validate(data, "qa_input")
        if result is None:
            raise ValidationError("QA input is not valid JSON")
        return result

    def validate_qa_output(self, data: dict[str, Any] | str) -> dict[str, Any]:
        """Validate QA review response."""

        result = self.validate(data, "qa_output")
        if result is None:
            raise ValidationError("QA output is not valid JSON")
        return result
