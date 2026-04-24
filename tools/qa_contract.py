"""QA agent contract helpers.

Single source of truth for validating the JSON payloads that flow
between the orchestrator and the QA agent:

- `validate_qa_output` : agent -> orchestrator response.
- `validate_qa_input`  : orchestrator -> agent request.

Output validation performs JSON Schema checks plus the structural checks
JSON Schema cannot express (status-conditional verdict/rejection-reason
invariants). Input validation is pure JSON Schema; the schema already
encodes every cross-field invariant that exists on the input side
(e.g. the Engineer output must carry `status == "implemented"`).

The CLIs in `tools/validate_qa_output.py` and `tools/validate_qa_input.py`
wrap these functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
DEFAULT_OUTPUT_SCHEMA_PATH = _SCHEMAS_DIR / "qa_output.schema.json"
DEFAULT_INPUT_SCHEMA_PATH = _SCHEMAS_DIR / "qa_input.schema.json"


class ContractValidationError(ValueError):
    """Raised when a QA payload fails schema or structural checks."""


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


def _iter_verdicts(findings: dict[str, Any]) -> list[str]:
    """Flatten every verdict from findings into a single list."""
    verdicts = [f["verdict"] for f in findings["functional"]]
    for category in ("solid", "yagni_kiss", "testing"):
        verdicts.append(findings[category]["verdict"])
    return verdicts


def _validate_output_structural(payload: dict[str, Any]) -> None:
    """Enforce status-conditional invariants that JSON Schema does not.

    - status == "approved": rejection_reasons empty; every finding verdict
      is "met".
    - status == "rejected": rejection_reasons non-empty; at least one
      finding verdict is "unmet" or "uncertain".
    """
    status = payload["status"]
    rejection_reasons = payload["rejection_reasons"]
    verdicts = _iter_verdicts(payload["findings"])

    if status == "approved":
        if rejection_reasons:
            raise ContractValidationError(
                "`rejection_reasons` must be empty when status is `approved`."
            )
        if any(v != "met" for v in verdicts):
            raise ContractValidationError(
                "All finding verdicts must be `met` when status is `approved`."
            )
    elif status == "rejected":
        if not rejection_reasons:
            raise ContractValidationError(
                "`rejection_reasons` must be non-empty when status is `rejected`."
            )
        if all(v == "met" for v in verdicts):
            raise ContractValidationError(
                "At least one finding verdict must be `unmet` or `uncertain` "
                "when status is `rejected`."
            )


def validate_qa_output(
    payload: dict[str, Any],
    schema_path: Path | None = None,
) -> None:
    """Validate a QA output payload end-to-end."""
    _validate_json_schema(payload, schema_path or DEFAULT_OUTPUT_SCHEMA_PATH)
    _validate_output_structural(payload)


def validate_qa_input(
    payload: dict[str, Any],
    schema_path: Path | None = None,
) -> None:
    """Validate a QA input payload against the JSON Schema."""
    _validate_json_schema(payload, schema_path or DEFAULT_INPUT_SCHEMA_PATH)


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ContractValidationError("Top-level JSON value must be an object.")
    return data
