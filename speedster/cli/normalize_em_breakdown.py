#!/usr/bin/env python3
"""CLI to normalize an EM breakdown JSON in place or to stdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from speedster.contracts.em_breakdown import (
    BreakdownValidationError,
    load_breakdown,
    normalize_breakdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize EM breakdown JSON (stable ordering and deduped lists).",
    )
    parser.add_argument("breakdown", help="Path to breakdown JSON to normalize.")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file instead of writing to stdout.",
    )
    args = parser.parse_args()

    path = Path(args.breakdown)
    if not path.exists():
        print(f"ERROR: breakdown file not found: {path}", file=sys.stderr)
        return 2

    try:
        payload = load_breakdown(path)
        normalized = normalize_breakdown(payload)
    except BreakdownValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
    if args.in_place:
        path.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
