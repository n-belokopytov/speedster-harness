#!/usr/bin/env bash
#
# setup.sh - Orchestrator for speedster-harness setup
#
# Sources shared library and phase scripts, then executes phases in order.
#
# Usage: ./setup.sh [OPTIONS]
#
# Options:
#   --phase <name>        Run only one phase
#   --agents-url <url>    Set all agent URLs to the same value
#   --skip-docker-start   Skip auto-starting Docker containers
#   --url <url>           Model endpoint URL (triggers pi phase)
#   --skip-validate       Skip the validate phase
#   --dry-run             Print commands without executing
#   --help                Show this message
#

# shellcheck source=./setup/lib.sh
source "$(dirname "$0")/setup/lib.sh"

PHASES=("prerequisites" "venv" "dependencies" "precommit" "directories" "dockercompose" "pi" "validate")

# --- Defaults ---
DRY_RUN="${DRY_RUN:-0}"
SKIP_VALIDATE="${SKIP_VALIDATE:-0}"
SKIP_DOCKER_START="${SKIP_DOCKER_START:-0}"
SINGLE_PHASE="${SINGLE_PHASE:-}"
URL="${URL:-}"
AGENTS_URL="${AGENTS_URL:-}"

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
  dockercompose   Set up Docker Compose with agent URLs (requires docker)
  pi              Configure PI with model endpoint (requires --url)
  validate        Run pytest to confirm environment is working

Options:
  --phase <name>    Run only one phase (prerequisites|venv|dependencies|
                      precommit|directories|dockercompose|pi|validate)
  --agents-url <url> Set all agent URLs to the same value
  --skip-docker-start  Skip auto-starting Docker containers
  --url <url>     Model endpoint URL (triggers pi phase)
  --skip-validate   Skip the validate phase
  --dry-run         Print commands without executing
  --help            Show this message

Environment variables (passed through to pi-setup.sh):
  API_KEY             API key for the model endpoint
  MODEL               Override automatic model detection
  AUTO_INSTALL_PI     Set to 0 to disable auto-install

Examples:
  ./setup.sh                              # Full setup
  ./setup.sh --agents-url http://host:9000
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
            --skip-docker-start)
                SKIP_DOCKER_START=1
                shift
                ;;
            --agents-url)
                AGENTS_URL="$2"
                shift 2
                ;;
            --skip-validate)
                SKIP_VALIDATE=1
                shift
                ;;
            --phase)
                SINGLE_PHASE="$2"
                SINGLE_PHASE="${SINGLE_PHASE/pre-commit/precommit}"
                shift 2
                ;;
            --url)
                URL="$2"
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
        local valid=0
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

# --- Phase: pi (inline, delegates to pi-setup.sh) ---
phase_pi() {
    step "Configuring PI with model endpoint"

    if [[ -z "$URL" ]]; then
        info "No --url specified, skipping pi phase"
        info "To configure: ./setup.sh --url <endpoint_base_url>"
        return 0
    fi

    local setup_script="${SCRIPT_DIR}/pi-setup.sh"
    if [[ ! -f "$setup_script" ]]; then
        fail "pi-setup.sh not found at ${setup_script}"
        return 1
    fi

    if [[ ! -x "$setup_script" ]] && [[ "$DRY_RUN" -eq 0 ]]; then
        echo "  Making pi-setup.sh executable..."
        chmod +x "$setup_script"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        cmd "${setup_script} ${URL}"
        return 0
    fi

    echo "  Delegating to pi-setup.sh with URL: ${URL}"
    bash "$setup_script" "$URL"
}

# --- Source all phase scripts ---
for phase in "${PHASES[@]}"; do
    # pi is defined inline above
    if [[ "$phase" != "pi" ]]; then
        local_script="${SCRIPT_DIR}/setup/${phase}.sh"
        if [[ -f "$local_script" ]]; then
            # shellcheck source=setup/prerequisites.sh
            # shellcheck source=setup/venv.sh
            # shellcheck source=setup/dependencies.sh
            # shellcheck source=setup/precommit.sh
            # shellcheck source=setup/directories.sh
            # shellcheck source=setup/dockercompose.sh
            # shellcheck source=setup/validate.sh
            source "$local_script"
        else
            fail "Phase script not found: ${local_script}" >&2
            exit 1
        fi
    fi
done

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
        if [[ "$phase" == "validate" ]] && [[ "$SKIP_VALIDATE" -eq 1 ]]; then
            continue
        fi

        if [[ -n "$SINGLE_PHASE" ]] && [[ "$phase" != "$SINGLE_PHASE" ]]; then
            continue
        fi

        if "phase_${phase}"; then
            :
        else
            failed+=("$phase")
            if [[ "$phase" == "pi" ]]; then
                info "pi phase would exec pi-setup.sh"
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
