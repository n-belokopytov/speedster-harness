#!/usr/bin/env bash
#
# setup/venv.sh - Create Python virtual environment
#
# Usage:
#   source setup/lib.sh && source setup/venv.sh             # sourced by orchestrator
#   ./setup/venv.sh                                         # standalone
#

phase_venv() {
    step "Setting up Python virtual environment"

    resolve_python_bin

    if [[ -d "$VENV_DIR" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python3"
        if [[ ! -x "$PYTHON_BIN" ]]; then
            PYTHON_BIN="${VENV_DIR}/bin/python"
        fi
        if [[ -x "$PYTHON_BIN" ]]; then
            state_set PYTHON_BIN "$PYTHON_BIN"
            pass "Virtual environment already exists at ${VENV_DIR}"

            if [[ "${VIRTUAL_ENV:-}" == "$VENV_DIR" ]]; then
                info "Virtual environment is active"
            else
                info "Activate with: source ${VENV_DIR}/bin/activate"
            fi
            return 0
        fi
    fi

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        cmd "python3 -m venv ${VENV_DIR}"
    else
        echo "  Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi

    PYTHON_BIN="${VENV_DIR}/bin/python3"
    if [[ ! -x "$PYTHON_BIN" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python"
    fi
    state_set PYTHON_BIN "$PYTHON_BIN"

    if [[ -x "$PYTHON_BIN" ]]; then
        pass "Virtual environment created at ${VENV_DIR}"
    else
        fail "Failed to create virtual environment"
        return 1
    fi
}
