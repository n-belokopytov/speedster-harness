#!/usr/bin/env python3
"""CLI for QA output validation (schema + structural)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from speedster.contracts.qa_contract import (
    DEFAULT_OUTPUT_SCHEMA_PATH,
    ContractValidationError,
    load_payload,
    validate_qa_output,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate QA output JSON (schema + structural).",
    )
    parser.add_argument("payload", help="Path to QA output JSON to validate.")
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_OUTPUT_SCHEMA_PATH),
        help="Path to JSON schema file.",
    )
    args = parser.parse_args()

    payload_path = Path(args.payload)
    schema_path = Path(args.schema)

    if not payload_path.exists():
        print(f"ERROR: payload file not found: {payload_path}", file=sys.stderr)
        return 2
    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        return 2

    try:
        payload = load_payload(payload_path)
        validate_qa_output(payload, schema_path=schema_path)
    except ContractValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI wants concise error output
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print("VALID: qa output passes schema and structural checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
