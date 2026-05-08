#!/usr/bin/env bash
#
# setup/directories.sh - Create required directories
#
# Usage:
#   source setup/lib.sh && source setup/directories.sh      # sourced by orchestrator
#   ./setup/directories.sh                                  # standalone
#

phase_directories() {
    step "Creating required directories"

    local -a dirs=("state/snapshots" "tasks")
    local ok=0

    for dir in "${dirs[@]}"; do
        local full="${SCRIPT_DIR}/${dir}"
        if [[ -d "$full" ]]; then
            pass "${dir}/ exists"
        else
            if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
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
