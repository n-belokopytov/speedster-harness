#!/usr/bin/env bash
#
# setup/prerequisites.sh - Check for required system tools
#
# Usage:
#   source setup/lib.sh && source setup/prerequisites.sh   # sourced by orchestrator
#   ./setup/prerequisites.sh                                # standalone
#

phase_prerequisites() {
    step "Checking prerequisites"

    local missing=0
    local -a hard=(git curl)

    for c in "${hard[@]}"; do
        if has_cmd "$c"; then
            pass "$c found"
        else
            fail "$c not found (required)"
            missing=1
        fi
    done

    if has_cmd python3; then
        pass "python3 found"
    else
        fail "python3 not found (required)"
        missing=1
    fi

    if python3 -m pip --version >/dev/null 2>&1; then
        pass "pip found (python3 -m pip)"
    else
        fail "pip not found (required — try: python3 -m ensurepip)"
        missing=1
    fi

    if has_cmd python3; then
        local py_ver
        py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
            pass "Python ${py_ver} >= 3.12"
        else
            fail "Python ${py_ver} < 3.12 (required)"
            missing=1
        fi
    fi

    for c in shellcheck npm docker; do
        if has_cmd "$c"; then
            pass "$c found (optional)"
        else
            warn "$c not found (optional)"
        fi
    done

    [[ "$missing" -eq 0 ]]
}
