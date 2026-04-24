#!/usr/bin/env bash
#
# setup/dockercompose.sh - Set up Docker Compose with agent URLs
#
# Usage:
#   source setup/lib.sh && source setup/dockercompose.sh    # sourced by orchestrator
#   ./setup/dockercompose.sh [--agents-url <url>]           # standalone
#

phase_dockercompose() {
    step "Setting up Docker Compose"

    if ! has_cmd docker; then
        fail "docker not found (required for Docker Compose setup)"
        return 1
    fi

    if ! docker compose version >/dev/null 2>&1; then
        fail "docker compose not available (install Docker Compose plugin)"
        return 1
    fi

    local docker_compose_file="${SCRIPT_DIR}/docker-compose.yml"
    if [[ ! -f "$docker_compose_file" ]]; then
        fail "docker-compose.yml not found"
        return 1
    fi

    local env_file="${SCRIPT_DIR}/.env"
    local env_example="${SCRIPT_DIR}/.env.example"

    if [[ ! -f "$env_file" ]]; then
        if [[ -f "$env_example" ]]; then
            echo "  Creating .env from template..."
            if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
                cmd "cp ${env_example} ${env_file}"
            else
                cp "$env_example" "$env_file"
                pass ".env created from template"
            fi
        else
            warn ".env.example not found, creating empty .env"
            if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
                cmd "touch ${env_file}"
            else
                touch "$env_file"
            fi
        fi
    fi

    # Prompt for agent URLs
    local em_url eng_url qa_url

    if [[ -n "${AGENTS_URL:-}" ]]; then
        info "Using --agents-url for all agents: ${AGENTS_URL}"
        em_url="$AGENTS_URL"
        eng_url="$AGENTS_URL"
        qa_url="$AGENTS_URL"
    else
        # Read existing URLs from .env if available
        local existing_em="" existing_eng="" existing_qa=""
        if [[ -f "$env_file" ]]; then
            existing_em="$(grep -E '^EM_AGENT_URL=' "$env_file" 2>/dev/null | cut -d= -f2- || echo "")"
            existing_eng="$(grep -E '^ENG_AGENT_URL=' "$env_file" 2>/dev/null | cut -d= -f2- || echo "")"
            existing_qa="$(grep -E '^QA_AGENT_URL=' "$env_file" 2>/dev/null | cut -d= -f2- || echo "")"
        fi

        local em_default="${existing_em:-http://localhost:8081}"
        info "EM Agent URL [${em_default}]:"
        read -r em_input
        em_url="${em_input:-$em_default}"

        local eng_default="${existing_eng:-http://localhost:8082}"
        info "Engineer Agent URL [${eng_default}]:"
        read -r eng_input
        eng_url="${eng_input:-$eng_default}"

        local qa_default="${existing_qa:-http://localhost:8083}"
        info "QA Agent URL [${qa_default}]:"
        read -r qa_input
        qa_url="${qa_input:-$qa_default}"
    fi

    # Validate URLs
    for url in "$em_url" "$eng_url" "$qa_url"; do
        if [[ ! "$url" =~ ^https?:// ]]; then
            fail "Invalid URL: ${url} (must start with http:// or https://)"
            return 1
        fi
    done

    # Write URLs to .env file
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        cmd "Writing agent URLs to .env"
    else
        _update_env_var() {
            local key="$1" value="$2"
            if grep -q "^${key}=" "$env_file" 2>/dev/null; then
                sed -i.bak "s|^${key}=.*|${key}=${value}|" "$env_file" && rm -f "${env_file}.bak"
            else
                echo "${key}=${value}" >> "$env_file"
            fi
        }

        _update_env_var "EM_AGENT_URL" "$em_url"
        _update_env_var "ENG_AGENT_URL" "$eng_url"
        _update_env_var "QA_AGENT_URL" "$qa_url"

        # Extract ports from URLs
        local em_port eng_port qa_port
        em_port="$(echo "$em_url" | grep -oE '[0-9]+$')"
        eng_port="$(echo "$eng_url" | grep -oE '[0-9]+$')"
        qa_port="$(echo "$qa_url" | grep -oE '[0-9]+$')"

        [[ -n "$em_port" ]] && _update_env_var "EM_AGENT_PORT" "$em_port"
        [[ -n "$eng_port" ]] && _update_env_var "ENG_AGENT_PORT" "$eng_port"
        [[ -n "$qa_port" ]] && _update_env_var "QA_AGENT_PORT" "$qa_port"

        pass "Agent URLs written to .env"
    fi

    # Auto-start containers
    if [[ "${SKIP_DOCKER_START:-0}" -eq 1 ]]; then
        info "Skipping Docker start (--skip-docker-start)"
        return 0
    fi

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        cmd "docker compose up -d --build"
        return 0
    fi

    echo "  Building and starting agent containers..."
    if docker compose -f "$docker_compose_file" up -d --build; then
        pass "Agent containers started"
        echo "  "
        echo "  Agent endpoints:"
        echo "    EM:        ${em_url}"
        echo "    Engineer:  ${eng_url}"
        echo "    QA:        ${qa_url}"
        echo "  "
        info "View logs with: docker compose logs -f"
    else
        fail "Failed to start agent containers"
        return 1
    fi
}

# Standalone execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    source "$(dirname "$0")/lib.sh"
    DRY_RUN="${DRY_RUN:-0}"
    SKIP_DOCKER_START="${SKIP_DOCKER_START:-0}"
    AGENTS_URL="${AGENTS_URL:-}"

    # Parse args for standalone mode
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --agents-url) AGENTS_URL="$2"; shift 2 ;;
            --skip-docker-start) SKIP_DOCKER_START=1; shift ;;
            --dry-run) DRY_RUN=1; shift ;;
            *) shift ;;
        esac
    done

    phase_dockercompose
    exit $?
fi
