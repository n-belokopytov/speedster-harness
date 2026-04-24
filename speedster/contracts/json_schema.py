"""Shared JSON Schema validation helper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_json_schema(payload: dict[str, Any], schema_path: Path) -> None:
    """Validate a payload against a JSON Schema file.

    Args:
        payload: The JSON object to validate
        schema_path: Path to the JSON Schema file

    Raises:
        jsonschema.ValidationError: If the payload doesn't match the schema
        RuntimeError: If jsonschema is not installed
    """

    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `jsonschema`. Install with: pip install jsonschema"
        ) from exc

    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    jsonschema.validate(instance=payload, schema=schema)
