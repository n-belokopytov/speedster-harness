#!/usr/bin/env bash
#
# setup.sh - Comprehensive project setup for speedster-harness
#
# Bootstraps the full development environment:
#   1. Checks prerequisites (python3, pip, git, curl)
#   2. Creates a local Python virtual environment
#   3. Installs the speedster package and test dependencies
#   4. Installs pre-commit hooks (phase: precommit)
#   5. Creates required directories
#   6. Optionally configures OpenCode with a vLLM instance
#   7. Runs pytest to validate the environment
#
# Usage: ./setup.sh [OPTIONS]
#
# Options:
#   --phase <name>    Run only one phase: prerequisites|venv|dependencies|
#                     precommit|directories|opencode|validate
#   --vllm-url <url>  vLLM base URL (triggers opencode phase, passed to
#                     opencode-setup.sh)
#   --skip-validate   Skip the validate phase
#   --dry-run         Print commands without executing
#   --help            Show this message
#

set -uo pipefail

# --- Globals ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON_BIN=""
VENV_PIP=""

DRY_RUN=0
VERBOSE=0
SKIP_VALIDATE=0
SINGLE_PHASE=""
VLLM_URL=""

PHASES=("prerequisites" "venv" "dependencies" "precommit" "directories" "opencode" "validate")

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

run_cmd() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        cmd "$*"
    else
        echo "  $*"
        "$@"
    fi
}

# --- Usage ---
usage() {
    cat <<'EOF'
Usage: ./setup.sh [OPTIONS]

Comprehensive project setup for speedster-harness.

Phases (executed in order):
  prerequisites   Check for required system tools
  venv            Create Python virtual environment
  dependencies    Install speedster package and test dependencies
  pre-commit      Install pre-commit hooks
  directories     Ensure state/ and tasks/ directories exist
  opencode        Configure OpenCode with vLLM (requires --vllm-url)
  validate        Run pytest to confirm environment is working

Options:
  --phase <name>    Run only one phase (prerequisites|venv|dependencies|
                    precommit|directories|opencode|validate)
  --vllm-url <url>  vLLM base URL (triggers opencode phase)
  --skip-validate   Skip the validate phase
  --dry-run         Print commands without executing
  --help            Show this message

Environment variables (passed through to opencode-setup.sh):
  VLLM_API_KEY          API key for vLLM authentication
  MODEL                 Override automatic model detection
  AUTO_INSTALL_OPENCODE Set to 0 to disable auto-install

Examples:
  ./setup.sh                              # Full setup, skip opencode
  ./setup.sh --vllm-url http://localhost:8000/v1
  ./setup.sh --phase venv                 # Create venv only
  ./setup.sh --dry-run                    # Preview all steps
  ./setup.sh --skip-validate              # Skip pytest validation
EOF
}

# --- Argument parsing ---
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help)
                usage
                exit 0
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            --verbose)
                VERBOSE=1
                shift
                ;;
            --skip-validate)
                SKIP_VALIDATE=1
                shift
                ;;
            --phase)
                SINGLE_PHASE="$2"
                # Accept both "pre-commit" and "precommit"
                SINGLE_PHASE="${SINGLE_PHASE/pre-commit/precommit}"
                shift 2
                ;;
            --vllm-url)
                VLLM_URL="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1" >&2
                usage >&2
                exit 1
                ;;
        esac
    done

    if [[ -n "$SINGLE_PHASE" ]]; then
        valid=0
        for p in "${PHASES[@]}"; do
            if [[ "$p" == "$SINGLE_PHASE" ]]; then
                valid=1
                break
            fi
        done
        if [[ "$valid" -eq 0 ]]; then
            echo "ERROR: unknown phase '$SINGLE_PHASE'" >&2
            echo "Valid phases: ${PHASES[*]}" >&2
            exit 1
        fi
    fi
}

# --- Phases ---

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

    # Check python3 (required)
    if has_cmd python3; then
        pass "python3 found"
    else
        fail "python3 not found (required)"
        missing=1
    fi

    # Check pip via python3 -m pip (works even when pip binary isn't on PATH)
    if python3 -m pip --version >/dev/null 2>&1; then
        pass "pip found (python3 -m pip)"
    else
        fail "pip not found (required — try: python3 -m ensurepip)"
        missing=1
    fi

    # Check Python version >= 3.12
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

    # Optional tools
    for c in shellcheck npm; do
        if has_cmd "$c"; then
            pass "$c found (optional)"
        else
            warn "$c not found (optional)"
        fi
    done

    [[ "$missing" -eq 0 ]]
}

phase_venv() {
    step "Setting up Python virtual environment"

    if [[ -d "$VENV_DIR" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python3"
        if [[ ! -x "$PYTHON_BIN" ]]; then
            PYTHON_BIN="${VENV_DIR}/bin/python"
        fi
        if [[ -x "$PYTHON_BIN" ]]; then
            pass "Virtual environment already exists at ${VENV_DIR}"

            # Check if venv is active
            if [[ "${VIRTUAL_ENV:-}" == "$VENV_DIR" ]]; then
                info "Virtual environment is active"
            else
                info "Activate with: source ${VENV_DIR}/bin/activate"
            fi
            return 0
        fi
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        cmd "python3 -m venv ${VENV_DIR}"
    else
        echo "  Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi

    PYTHON_BIN="${VENV_DIR}/bin/python3"
    VENV_PIP="${VENV_DIR}/bin/pip"

    if [[ -x "$PYTHON_BIN" ]]; then
        pass "Virtual environment created at ${VENV_DIR}"
    else
        fail "Failed to create virtual environment"
        return 1
    fi
}

phase_dependencies() {
    step "Installing dependencies"

    if [[ -z "$PYTHON_BIN" ]] && [[ -d "$VENV_DIR" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python3"
        if [[ ! -x "$PYTHON_BIN" ]]; then
            PYTHON_BIN="${VENV_DIR}/bin/python"
        fi
    fi

    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="python3"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
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

phase_precommit() {
    step "Installing pre-commit hooks"

    if [[ -z "$PYTHON_BIN" ]] && [[ -d "$VENV_DIR" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python3"
        if [[ ! -x "$PYTHON_BIN" ]]; then
            PYTHON_BIN="${VENV_DIR}/bin/python"
        fi
    fi

    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="python3"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
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

phase_directories() {
    step "Creating required directories"

    local -a dirs=("state/snapshots" "tasks")
    local ok=0

    for dir in "${dirs[@]}"; do
        local full="${SCRIPT_DIR}/${dir}"
        if [[ -d "$full" ]]; then
            pass "${dir}/ exists"
        else
            if [[ "$DRY_RUN" -eq 1 ]]; then
                cmd "mkdir -p ${full}"
            else
                mkdir -p "$full"
                if [[ -d "$full" ]]; then
                    pass "${dir}/ created"
                else
                    fail "Failed to create ${dir}/"
                    ok=1
                fi
            fi
        fi
    done

    [[ "$ok" -eq 0 ]]
}

phase_opencode() {
    step "Configuring OpenCode with vLLM"

    if [[ -z "$VLLM_URL" ]]; then
        info "No --vllm-url specified, skipping opencode phase"
        info "To configure: ./setup.sh --vllm-url <vllm_base_url>"
        return 0
    fi

    local setup_script="${SCRIPT_DIR}/opencode-setup.sh"
    if [[ ! -f "$setup_script" ]]; then
        fail "opencode-setup.sh not found at ${setup_script}"
        return 1
    fi

    if [[ ! -x "$setup_script" ]] && [[ "$DRY_RUN" -eq 0 ]]; then
        echo "  Making opencode-setup.sh executable..."
        chmod +x "$setup_script"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        cmd "${setup_script} ${VLLM_URL}"
        return 0
    fi

    echo "  Delegating to opencode-setup.sh with URL: ${VLLM_URL}"
    exec bash "$setup_script" "$VLLM_URL"
}

phase_validate() {
    step "Validating environment with pytest"

    if [[ "$SKIP_VALIDATE" -eq 1 ]]; then
        info "Validation skipped (--skip-validate)"
        return 0
    fi

    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python3"
        if [[ ! -x "$PYTHON_BIN" ]]; then
            PYTHON_BIN="${VENV_DIR}/bin/python"
        fi
    fi

    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="python3"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
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

# --- Main ---

main() {
    parse_args "$@"

    echo ""
    info "speedster-harness setup"
    info "====================="

    if [[ "$DRY_RUN" -eq 1 ]]; then
        info "Mode: dry-run (no changes will be made)"
    fi
    if [[ -n "$SINGLE_PHASE" ]]; then
        info "Phase: ${SINGLE_PHASE} only"
    fi

    local -a failed=()
    local phase

    for phase in "${PHASES[@]}"; do
        # Skip validate if requested
        if [[ "$phase" == "validate" ]] && [[ "$SKIP_VALIDATE" -eq 1 ]]; then
            continue
        fi

        # Skip phases when running a single phase
        if [[ -n "$SINGLE_PHASE" ]] && [[ "$phase" != "$SINGLE_PHASE" ]]; then
            continue
        fi

        if "phase_${phase}"; then
            :
        else
            failed+=("$phase")
            if [[ "$phase" == "opencode" ]]; then
                # opencode uses exec, so we only reach here on dry-run
                info "opencode phase would exec opencode-setup.sh"
            fi
        fi
    done

    echo ""
    info "Setup complete"

    if [[ ${#failed[@]} -gt 0 ]]; then
        echo -e "${RED}Failed phases: ${failed[*]}${NC}" >&2
        exit 1
    else
        pass "All phases completed successfully"
    fi
}

main "$@"
