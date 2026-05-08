#!/usr/bin/env bash
#
# setup/dockercompose.sh - Set up Docker Compose with default agent URLs
#
# Agent URLs are fixed:
#   EM:        http://localhost:8081
#   Engineer:  http://localhost:8082
#   QA:        http://localhost:8083
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

    # Fixed agent URLs
    local em_url="http://localhost:8081"
    local eng_url="http://localhost:8082"
    local qa_url="http://localhost:8083"

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
        _update_env_var "EM_AGENT_PORT" "8081"
        _update_env_var "ENG_AGENT_PORT" "8082"
        _update_env_var "QA_AGENT_PORT" "8083"

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
