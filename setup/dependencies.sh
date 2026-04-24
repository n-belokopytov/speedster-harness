#!/usr/bin/env bash
#
# setup/dependencies.sh - Install speedster package and test dependencies
#
# Usage:
#   source setup/lib.sh && source setup/dependencies.sh     # sourced by orchestrator
#   ./setup/dependencies.sh                                 # standalone
#

phase_dependencies() {
    step "Installing dependencies"

    resolve_python_bin

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        cmd "python -m pip install -e '.[test]'"
        return 0
    fi

    echo "  Installing speedster package and test dependencies..."
    local install_path="${SCRIPT_DIR}[test]"
    if "$PYTHON_BIN" -m pip install -e "$install_path"; then
        pass "Dependencies installed"
    else
        fail "Dependency installation failed"
        return 1
    fi
}

# Standalone execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    source "$(dirname "$0")/lib.sh"
    DRY_RUN="${DRY_RUN:-0}"
    phase_dependencies
    exit $?
fi
