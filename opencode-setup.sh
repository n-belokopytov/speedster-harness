#!/usr/bin/env bash
set -euo pipefail

# Usage: ./opencode-setup.sh <vllm_base_url>
# Example: ./opencode-setup.sh http://localhost:8000/v1
#
# Optional env vars:
#   VLLM_API_KEY=your-key          # optional; default is empty = no Authorization header
#   MODEL=exact/model/id           # optional; auto-detected from /v1/models if omitted
#   AUTO_INSTALL_OPENCODE=1        # set to 0 to disable auto-install

VLLM_BASE_URL="${1:?Usage: $0 <vllm_base_url>}"
VLLM_API_KEY="${VLLM_API_KEY:-}"
AUTO_INSTALL_OPENCODE="${AUTO_INSTALL_OPENCODE:-1}"
MODEL="${MODEL:-}"

# Config path
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$XDG_CONFIG_HOME/opencode}"
OPENCODE_CONFIG_PATH="${OPENCODE_CONFIG_PATH:-$OPENCODE_CONFIG_DIR/opencode.json}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: required command not found: $1" >&2; exit 1; }
}

json_escape() {
  python3 - "$1" <<'PY'
import json, sys
print(json.dumps(sys.argv[1]))
PY
}

echo "==> Checking prerequisites"
need_cmd curl
need_cmd python3

# Validate URL scheme (only http/https)
if echo "$VLLM_BASE_URL" | grep -qE "^(https?://)[a-zA-Z0-9][a-zA-Z0-9._:-]*:[0-9]+(/v[0-9]+)?$"; then
  :
elif echo "$VLLM_BASE_URL" | grep -qE "^[a-zA-Z0-9][a-zA-Z0-9._:-]+:[0-9]+$"; then
  VLLM_BASE_URL="http://$VLLM_BASE_URL"
else
  echo "ERROR: invalid vLLM base URL. Expected: <scheme>://host:port" >&2
  exit 1
fi

VLLM_BASE_URL="${VLLM_BASE_URL%/}"

echo "==> Checking vLLM endpoint: ${VLLM_BASE_URL}/models"

CURL_ARGS=(-fsS)
[[ -n "$VLLM_API_KEY" ]] && CURL_ARGS+=(-H "Authorization: Bearer ${VLLM_API_KEY}")

MODELS_JSON="$(curl "${CURL_ARGS[@]}" "${VLLM_BASE_URL}/models")" || {
  echo "ERROR: could not reach vLLM at ${VLLM_BASE_URL}/models" >&2
  echo "Check: vLLM is running, base URL includes /v1, scheme correct" >&2
  exit 1
}

# Auto-detect model if not specified
[[ -z "${MODEL}" ]] && MODEL="$(python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0]['id'])" <<< "$MODELS_JSON")"

[[ -z "${MODEL}" ]] && { echo "ERROR: could not determine model name" >&2; exit 1; }

echo "==> Found model: ${MODEL}"

# Validate model name (alphanumeric, dash, underscore, slash, dot only)
[[ ! "${MODEL}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_./-]*$ ]] && { echo "ERROR: invalid model name: ${MODEL}" >&2; exit 1; }

# Create config directory with secure permissions
mkdir -p "${OPENCODE_CONFIG_DIR}"
chmod 700 "${OPENCODE_CONFIG_DIR}"

# Backup existing config
if [[ -f "${OPENCODE_CONFIG_PATH}" ]]; then
  BACKUP_PATH="${OPENCODE_CONFIG_PATH}.bak.$(date +%Y%m%d-%H%M%S)"
  cp "${OPENCODE_CONFIG_PATH}" "${BACKUP_PATH}"
  chmod 600 "${BACKUP_PATH}"
  echo "==> Existing config backed up to ${BACKUP_PATH}"
fi

# Generate config
MODEL_ESCAPED="$(json_escape "${MODEL}")"
BASE_URL_ESCAPED="$(json_escape "${VLLM_BASE_URL}")"

TEMP_CONFIG="$(mktemp)"
cat > "${TEMP_CONFIG}" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "vllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "vLLM (local)",
      "options": {
        "baseURL": ${BASE_URL_ESCAPED}
      },
      "models": {
        ${MODEL_ESCAPED}: { "name": ${MODEL_ESCAPED} }
      }
    }
  },
  "model": vllm/${MODEL_ESCAPED},
  "permission": {
    "bash": "ask",
    "edit": "allow",
    "webfetch": "allow"
  }
}
EOF

chmod 600 "${TEMP_CONFIG}"
mv "${TEMP_CONFIG}" "${OPENCODE_CONFIG_PATH}"

# Validate config
if ! python3 -c "import json; json.load(open('${OPENCODE_CONFIG_PATH}'))" 2>/dev/null; then
  echo "ERROR: invalid config generated" >&2
  [[ -f "${BACKUP_PATH}" ]] && { mv "${BACKUP_PATH}" "${OPENCODE_CONFIG_PATH}" && echo "Restored backup" >&2; }
  exit 1
fi

echo "==> Wrote config to ${OPENCODE_CONFIG_PATH}"

# Install if needed
if ! command -v opencode >/dev/null 2>&1; then
  if [[ "${AUTO_INSTALL_OPENCODE}" == "1" ]]; then
    echo "==> Installing opencode..."
    need_cmd npm
    npm install -g opencode-ai || { echo "ERROR: failed to install opencode" >&2; exit 1; }
  else
    echo "ERROR: opencode is not installed. Install manually or use AUTO_INSTALL_OPENCODE=1" >&2
    exit 1
  fi
fi

# Export API key for opencode to use
[[ -n "${VLLM_API_KEY}" ]] && export OPC_API_KEY="${VLLM_API_KEY}"

echo
echo "==> Launching OpenCode with model: vllm/${MODEL}"
echo "==> Config file: ${OPENCODE_CONFIG_PATH}"
[[ -n "${VLLM_API_KEY}" ]] && echo "==> API key: via environment variable"
echo

exec opencode
