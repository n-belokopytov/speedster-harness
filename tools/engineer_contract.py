"""Engineer agent contract helpers.

Single source of truth for validating the JSON payloads that flow
between the orchestrator and the Engineer agent:

- `validate_engineer_output` : agent -> orchestrator response.
- `validate_engineer_input`  : orchestrator -> agent request.

Output validation performs JSON Schema checks plus the structural checks
JSON Schema cannot express (status-conditional field requirements). Input
validation is currently pure JSON Schema; no cross-field invariants remain
beyond what the schema expresses.

The CLIs in `tools/validate_engineer_output.py` and
`tools/validate_engineer_input.py` wrap these functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
DEFAULT_OUTPUT_SCHEMA_PATH = _SCHEMAS_DIR / "engineer_output.schema.json"
DEFAULT_INPUT_SCHEMA_PATH = _SCHEMAS_DIR / "engineer_input.schema.json"


class ContractValidationError(ValueError):
    """Raised when an Engineer payload fails schema or structural checks."""


def _validate_json_schema(payload: dict[str, Any], schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `jsonschema`. Install with: pip install jsonschema"
        ) from exc
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=payload, schema=schema)


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
    _validate_json_schema(payload, schema_path or DEFAULT_OUTPUT_SCHEMA_PATH)
    _validate_output_structural(payload)


def validate_engineer_input(
    payload: dict[str, Any],
    schema_path: Path | None = None,
) -> None:
    """Validate an Engineer input payload against the JSON Schema."""
    _validate_json_schema(payload, schema_path or DEFAULT_INPUT_SCHEMA_PATH)


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ContractValidationError("Top-level JSON value must be an object.")
    return data
