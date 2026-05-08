#!/usr/bin/env bash
#
# lib.sh - Shared utilities for setup scripts
#
# Sourced by setup.sh and each individual phase script.
# Provides color helpers, state management, argument parsing, and common functions.
#

set -uo pipefail

# --- Script directory resolution ---
_resolve_script_dir() {
    local src="${BASH_SOURCE[0]}"
    while [[ -L "$src" ]]; do
        local dir
        dir="$(cd "$(dirname "$src")" && pwd)"
        src="$(readlink "$src")"
        [[ "$src" != /* ]] && src="$dir/$src"
    done
    (cd "$(dirname "$src")" && pwd)
}

# LIB_DIR is setup/; SCRIPT_DIR is the project root
LIB_DIR="$(_resolve_script_dir)"
SCRIPT_DIR="$(cd "$LIB_DIR/.." && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

# --- State file ---
STATE_FILE="${SCRIPT_DIR}/.setup_state"

_setup_state_ensure() {
    if [[ ! -f "$STATE_FILE" ]]; then
        touch "$STATE_FILE"
    fi
}

state_get() {
    _setup_state_ensure
    grep -E "^${1}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || echo ""
}

state_set() {
    _setup_state_ensure
    local key="$1" value="$2"
    if grep -qE "^${key}=" "$STATE_FILE" 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$STATE_FILE" && rm -f "${STATE_FILE}.bak"
    else
        echo "${key}=${value}" >> "$STATE_FILE"
    fi
}

# --- Color helpers ---
RED=""
GREEN=""
YELLOW=""
NC=""
if [[ "${TERM:-}" != "dumb" ]] && [[ "${NO_COLOR:-}" == "" ]]; then
    RED=$'\e[31m'
    GREEN=$'\e[32m'
    YELLOW=$'\e[33m'
    NC=$'\e[0m'
fi

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1" >&2; }
info() { echo -e "  ${NC}$1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
step() { echo -e "\n${YELLOW}=== $1 ===${NC}"; }
cmd() { echo -e "  ${NC}\$ $*${NC}"; }

# --- Helpers ---
has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# Resolve PYTHON_BIN from state, venv, or fallback
resolve_python_bin() {
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        return
    fi
    PYTHON_BIN="$(state_get PYTHON_BIN)"
    if [[ -z "$PYTHON_BIN" ]] && [[ -d "$VENV_DIR" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python3"
        if [[ ! -x "$PYTHON_BIN" ]]; then
            PYTHON_BIN="${VENV_DIR}/bin/python"
        fi
        if [[ -x "$PYTHON_BIN" ]]; then
            state_set PYTHON_BIN "$PYTHON_BIN"
        fi
    fi
    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="python3"
    fi
}
