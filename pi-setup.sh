#!/usr/bin/env bash
set -euo pipefail

# Usage: ./pi-setup.sh <endpoint_url>
# Example: ./pi-setup.sh http://localhost:8000/v1
#
# Optional env vars:
#   API_KEY=your-key              # optional; API key for the endpoint
#   MODEL=exact/model/id          # optional; auto-detected from /models if omitted
#   AUTO_INSTALL_PI=1             # set to 0 to disable auto-install
#   PI_CONFIG_DIR=/path           # optional; overrides default config location ($HOME/.pi/agent)

ENDPOINT_URL="${1:?Usage: $0 <endpoint_url>}"
API_KEY="${API_KEY:-}"
AUTO_INSTALL_PI="${AUTO_INSTALL_PI:-1}"
MODEL="${MODEL:-}"

# Config paths
PI_CONFIG_DIR="${PI_CONFIG_DIR:-$HOME/.pi/agent}"

# Detect repo root and set up secondary config directory for Docker
REPO_PI_CONFIG_DIR=""
if [[ -f "$(pwd)/docker-compose.yml" ]]; then
  REPO_PI_CONFIG_DIR="$(pwd)/.pi/agent"
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: required command not found: $1" >&2; exit 1; }
}

echo "==> Checking prerequisites"
need_cmd curl
need_cmd python3

# Validate URL scheme (only http/https)
if echo "$ENDPOINT_URL" | grep -qE "^(https?://)[a-zA-Z0-9][a-zA-Z0-9._:-]*:[0-9]+(/v[0-9]+)?$"; then
  :
elif echo "$ENDPOINT_URL" | grep -qE "^[a-zA-Z0-9][a-zA-Z0-9._:-]+:[0-9]+$"; then
  ENDPOINT_URL="http://$ENDPOINT_URL"
else
  echo "ERROR: invalid endpoint URL. Expected: <scheme>://host:port" >&2
  exit 1
fi

ENDPOINT_URL="${ENDPOINT_URL%/}"

echo "==> Checking endpoint: ${ENDPOINT_URL}/models"

CURL_ARGS=(-fsS)
[[ -n "$API_KEY" ]] && CURL_ARGS+=(-H "Authorization: Bearer ${API_KEY}")

MODELS_JSON="$(curl "${CURL_ARGS[@]}" "${ENDPOINT_URL}/models")" || {
  echo "ERROR: could not reach endpoint at ${ENDPOINT_URL}/models" >&2
  echo "Check: the model server is running, base URL is correct" >&2
  exit 1
}

# Auto-detect model if not specified
[[ -z "${MODEL}" ]] && MODEL="$(python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0]['id'])" <<< "$MODELS_JSON")"

[[ -z "${MODEL}" ]] && { echo "ERROR: could not determine model name" >&2; exit 1; }

echo "==> Found model: ${MODEL}"

# Validate model name minimally
if [[ ! "${MODEL}" =~ ^[a-zA-Z0-9/_.@:-]+$ ]]; then
  echo "ERROR: invalid model name: ${MODEL}" >&2
  exit 1
fi

# Write config to a given directory
write_config_dir() {
  local target_dir="$1"
  local models_path="${target_dir}/models.json"
  local settings_path="${target_dir}/settings.json"

  # Create config directory with secure permissions
  mkdir -p "${target_dir}"
  chmod 700 "${target_dir}"

  # Backup existing models config
  if [[ -f "${models_path}" ]]; then
    BACKUP_PATH="${models_path}.bak.$(date +%Y%m%d-%H%M%S)"
    cp "${models_path}" "${BACKUP_PATH}"
    chmod 600 "${BACKUP_PATH}"
    echo "==> Existing models.json backed up to ${BACKUP_PATH}"
  fi

  # Generate models.json (OpenAI-compatible format)
  TEMP_MODELS="$(mktemp)"
  python3 - "$ENDPOINT_URL" "$MODEL" "$API_KEY" <<'PY' > "${TEMP_MODELS}"
import json, sys
import re

endpoint_url = sys.argv[1]
model_id = sys.argv[2]
api_key = sys.argv[3] if len(sys.argv) > 3 else ""

# Strip trailing /vN if present to get the base URL for the provider
base_url = endpoint_url.rstrip("/")
# If it ends with /v1, /v2, etc., strip it to get the true base
base_url = re.sub(r"/v\d+$", "", base_url)

options = {"baseURL": base_url + "/"}
if api_key:
    options["apiKey"] = api_key

config = {
    "provider": {
        "openai": {
            "name": "OpenAI Compatible",
            "options": options,
            "models": {
                model_id: {
                    "name": model_id,
                },
            },
        },
    },
}

print(json.dumps(config, indent=2))
PY

  chmod 600 "${TEMP_MODELS}"
  mv "${TEMP_MODELS}" "${models_path}"

  # Generate settings.json
  TEMP_SETTINGS="$(mktemp)"
  cat > "${TEMP_SETTINGS}" <<EOF
{
  "model": "${MODEL}",
  "permission": {
    "bash": "ask",
    "edit": "allow",
    "webfetch": "allow"
  }
}
EOF
  chmod 600 "${TEMP_SETTINGS}"
  mv "${TEMP_SETTINGS}" "${settings_path}"

  echo "==> Wrote models.json to ${models_path}"
  echo "==> Wrote settings.json to ${settings_path}"
}

# Write config to home directory
write_config_dir "${PI_CONFIG_DIR}"

# Also write to repo-local directory for Docker mounting
if [[ -n "${REPO_PI_CONFIG_DIR}" ]]; then
  echo
  echo "==> Writing repo-local config for Docker containers to ${REPO_PI_CONFIG_DIR}"
  write_config_dir "${REPO_PI_CONFIG_DIR}"
fi

# Install PI if needed
if ! command -v pi >/dev/null 2>&1; then
  if [[ "${AUTO_INSTALL_PI}" == "1" ]]; then
    echo "==> Installing PI..."
    need_cmd npm
    npm install -g @earendil-works/pi-coding-agent || { echo "ERROR: failed to install PI" >&2; exit 1; }
  else
    echo "ERROR: pi is not installed. Install manually or use AUTO_INSTALL_PI=1" >&2
    exit 1
  fi
fi

echo
echo "==> PI configured with model: ${MODEL}"
echo "==> Models config: ${PI_CONFIG_DIR}/models.json"
echo "==> Settings: ${PI_CONFIG_DIR}/settings.json"
if [[ -n "${API_KEY}" ]]; then
  echo "==> API key: persisted in models.json (options.apiKey)"
fi
if [[ -n "${REPO_PI_CONFIG_DIR}" ]]; then
  echo "==> Repo-local config: ${REPO_PI_CONFIG_DIR}/ (for Docker mounting)"
fi
echo
