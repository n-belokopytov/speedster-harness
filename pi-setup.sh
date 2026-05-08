#!/usr/bin/env bash
set -euo pipefail

# Usage: ./pi-setup.sh <endpoint_url>
# Example: ./pi-setup.sh http://localhost:8000/v1
#
# Optional env vars:
#   API_KEY=your-key              # optional; API key for the endpoint
#   MODEL=exact/model/id          # optional; auto-detected from /models if omitted
#   AUTO_INSTALL_PI=1             # set to 0 to disable auto-install

ENDPOINT_URL="${1:?Usage: $0 <endpoint_url>}"
API_KEY="${API_KEY:-}"
AUTO_INSTALL_PI="${AUTO_INSTALL_PI:-1}"
MODEL="${MODEL:-}"

# Config paths
PI_CONFIG_DIR="${PI_CONFIG_DIR:-$HOME/.pi/agent}"
PI_MODELS_PATH="${PI_CONFIG_DIR}/models.json"
PI_SETTINGS_PATH="${PI_CONFIG_DIR}/settings.json"

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
[[ "${MODEL}" =~ [[:space:][:cntrl:]] ]] && { echo "ERROR: invalid model name: ${MODEL}" >&2; exit 1; }

# Create config directory with secure permissions
mkdir -p "${PI_CONFIG_DIR}"
chmod 700 "${PI_CONFIG_DIR}"

# Backup existing models config
if [[ -f "${PI_MODELS_PATH}" ]]; then
  BACKUP_PATH="${PI_MODELS_PATH}.bak.$(date +%Y%m%d-%H%M%S)"
  cp "${PI_MODELS_PATH}" "${BACKUP_PATH}"
  chmod 600 "${BACKUP_PATH}"
  echo "==> Existing models.json backed up to ${BACKUP_PATH}"
fi

# Generate models.json (OpenAI-compatible format)
TEMP_MODELS="$(mktemp)"
python3 - "$ENDPOINT_URL" "$MODEL" <<'PY' > "${TEMP_MODELS}"
import json, sys

endpoint_url = sys.argv[1]
model_id = sys.argv[2]

# Strip trailing /vN if present to get the base URL for the provider
base_url = endpoint_url.rstrip("/")
# If it ends with /v1, /v2, etc., strip it to get the true base
import re
base_url = re.sub(r"/v\d+$", "", base_url)

config = {
    "provider": {
        "openai": {
            "name": "OpenAI Compatible",
            "options": {
                "baseURL": base_url + "/",
            },
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
mv "${TEMP_MODELS}" "${PI_MODELS_PATH}"

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
mv "${TEMP_SETTINGS}" "${PI_SETTINGS_PATH}"

echo "==> Wrote models.json to ${PI_MODELS_PATH}"
echo "==> Wrote settings.json to ${PI_SETTINGS_PATH}"

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

# Export API key for PI to use
[[ -n "${API_KEY}" ]] && export PI_API_KEY="${API_KEY}"

echo
echo "==> PI configured with model: ${MODEL}"
echo "==> Models config: ${PI_MODELS_PATH}"
echo "==> Settings: ${PI_SETTINGS_PATH}"
[[ -n "${API_KEY}" ]] && echo "==> API key: via environment variable"
echo
