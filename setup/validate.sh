#!/usr/bin/env bash
#
# setup/validate.sh - Run pytest to validate environment
#
# Usage:
#   source setup/lib.sh && source setup/validate.sh         # sourced by orchestrator
#   ./setup/validate.sh                                     # standalone
#

phase_validate() {
    step "Validating environment with pytest"

    if [[ "${SKIP_VALIDATE:-0}" -eq 1 ]]; then
        info "Validation skipped (--skip-validate)"
        return 0
    fi

    resolve_python_bin

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        cmd "python -m pytest tests/ -v"
        return 0
    fi

    echo "  Running tests..."
    if "$PYTHON_BIN" -m pytest tests/ -v; then
        pass "All tests passed"
    else
        fail "Tests failed"
        return 1
    fi
}
