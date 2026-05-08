"""Engineer agent contract helpers.

Validates the JSON payload that the Engineer agent returns to the
orchestrator (`validate_engineer_output`). Performs JSON Schema checks
plus structural checks JSON Schema cannot express (status-conditional
field requirements).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from speedster.contracts.json_schema import validate_json_schema

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
DEFAULT_OUTPUT_SCHEMA_PATH = _SCHEMAS_DIR / "engineer_output.schema.json"


class ContractValidationError(ValueError):
    """Raised when an Engineer payload fails schema or structural checks."""


def _validate_output_structural(payload: dict[str, Any]) -> None:
    """Enforce status-conditional invariants that JSON Schema does not.

    - status == "implemented": files_changed non-empty; blocked_reason empty;
      requested_context empty.
    - status == "blocked": blocked_reason non-empty; requested_context empty.
    - status == "needs_context": requested_context non-empty; blocked_reason
      empty; files_changed empty.
    """
    status = payload["status"]
    files_changed = payload["files_changed"]
    blocked_reason = payload["blocked_reason"]
    requested_context = payload["requested_context"]

    if status == "implemented":
        if not files_changed:
            raise ContractValidationError(
                "`files_changed` must be non-empty when status is `implemented`."
            )
        if blocked_reason:
            raise ContractValidationError(
                "`blocked_reason` must be empty when status is `implemented`."
            )
        if requested_context:
            raise ContractValidationError(
                "`requested_context` must be empty when status is `implemented`."
            )
    elif status == "blocked":
        if not blocked_reason:
            raise ContractValidationError(
                "`blocked_reason` must be non-empty when status is `blocked`."
            )
        if requested_context:
            raise ContractValidationError(
                "`requested_context` must be empty when status is `blocked`."
            )
    elif status == "needs_context":
        if not requested_context:
            raise ContractValidationError(
                "`requested_context` must be non-empty when status is `needs_context`."
            )
        if blocked_reason:
            raise ContractValidationError(
                "`blocked_reason` must be empty when status is `needs_context`."
            )
        if files_changed:
            raise ContractValidationError(
                "`files_changed` must be empty when status is `needs_context`."
            )


def validate_engineer_output(
    payload: dict[str, Any],
    schema_path: Path | None = None,
) -> None:
    """Validate an Engineer output payload end-to-end."""
    validate_json_schema(payload, schema_path or DEFAULT_OUTPUT_SCHEMA_PATH)
    _validate_output_structural(payload)
