#!/usr/bin/env python3
"""CLI for full EM breakdown validation (schema + structural + graph)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from em_breakdown import (
    DEFAULT_SCHEMA_PATH,
    BreakdownValidationError,
    load_breakdown,
    validate_breakdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate EM breakdown JSON (schema + structural + graph).",
    )
    parser.add_argument("breakdown", help="Path to breakdown JSON to validate.")
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to JSON schema file.",
    )
    args = parser.parse_args()

    breakdown_path = Path(args.breakdown)
    schema_path = Path(args.schema)

    if not breakdown_path.exists():
        print(f"ERROR: breakdown file not found: {breakdown_path}", file=sys.stderr)
        return 2
    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        return 2

    try:
        payload = load_breakdown(breakdown_path)
        validate_breakdown(payload, schema_path=schema_path)
    except BreakdownValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI wants concise error output
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print("VALID: breakdown passes schema, structural, and graph checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
