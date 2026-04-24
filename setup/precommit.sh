#!/usr/bin/env bash
#
# setup/precommit.sh - Install pre-commit hooks
#
# Usage:
#   source setup/lib.sh && source setup/precommit.sh        # sourced by orchestrator
#   ./setup/precommit.sh                                    # standalone
#

phase_precommit() {
    step "Installing pre-commit hooks"

    resolve_python_bin

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        cmd "python -m pip install pre-commit"
        cmd "pre-commit install"
        return 0
    fi

    if has_cmd pre-commit || "$PYTHON_BIN" -m pre_commit --version >/dev/null 2>&1; then
        :
    else
        echo "  Installing pre-commit..."
        if ! "$PYTHON_BIN" -m pip install pre-commit 2>&1 | grep -q "externally-managed"; then
            if ! "$PYTHON_BIN" -m pip install pre-commit; then
                fail "Failed to install pre-commit"
                return 1
            fi
        else
            if ! "$PYTHON_BIN" -m pip install --break-system-packages pre-commit; then
                fail "Failed to install pre-commit (try: source .venv/bin/activate && ./setup.sh --phase precommit)"
                return 1
            fi
        fi
    fi

    local pc_cmd
    if has_cmd pre-commit; then
        pc_cmd="pre-commit"
    else
        pc_cmd="$PYTHON_BIN -m pre_commit"
    fi

    if [[ -f "${SCRIPT_DIR}/.gitignore" ]]; then
        echo "  Installing git hooks..."
        if [[ "$pc_cmd" == *" -m "* ]]; then
            if $pc_cmd install; then
                pass "Pre-commit hooks installed"
            else
                fail "Failed to install pre-commit hooks"
                return 1
            fi
        else
            if "$pc_cmd" install; then
                pass "Pre-commit hooks installed"
            else
                fail "Failed to install pre-commit hooks"
                return 1
            fi
        fi
    else
        warn "Skipping: not in a git repository"
        return 0
    fi
}

# Standalone execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    source "$(dirname "$0")/lib.sh"
    DRY_RUN="${DRY_RUN:-0}"
    phase_precommit
    exit $?
fi
