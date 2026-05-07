"""Unified output validator for all agent roles.

Wraps the existing contracts validation libraries to provide a single
interface the orchestrator can use for validating agent input/output.
"""

from __future__ import annotations

import json
from typing import Any

from speedster.contracts.em_breakdown import (
    BreakdownValidationError,
    validate_breakdown as _validate_em_breakdown,
)
from speedster.contracts.engineer_contract import (
    ContractValidationError as EngineerContractError,
    validate_engineer_output as _validate_engineer_output,
)
from speedster.contracts.qa_contract import (
    ContractValidationError as QAContractError,
    validate_qa_output as _validate_qa_output,
)
from speedster.exceptions import ValidationError


class OutputValidator:
    """Central validator for all agent contracts.

    Validates agent input/output payloads against their respective
    JSON schemas and structural invariants.
    """

    OUTPUT_TYPES = {
        "em_breakdown": "EM planning output (breakdown tree)",
        "engineer_output": "Engineer -> Orchestrator response",
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

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict):
            raise ValidationError("Payload must be a JSON object")

        try:
            if output_type == "em_breakdown":
                _validate_em_breakdown(data)
            elif output_type == "engineer_output":
                _validate_engineer_output(data)
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
            raise ValidationError(str(exc)) from exc

    def validate_em_breakdown(self, data: dict[str, Any] | str) -> dict[str, Any]:
        result = self.validate(data, "em_breakdown")
        if result is None:
            raise ValidationError("EM output is not valid JSON")
        return result

    def validate_engineer_output(self, data: dict[str, Any] | str) -> dict[str, Any]:
        result = self.validate(data, "engineer_output")
        if result is None:
            raise ValidationError("Engineer output is not valid JSON")
        return result

    def validate_qa_output(self, data: dict[str, Any] | str) -> dict[str, Any]:
        result = self.validate(data, "qa_output")
        if result is None:
            raise ValidationError("QA output is not valid JSON")
        return result
