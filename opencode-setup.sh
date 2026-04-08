#!/usr/bin/env bash
set -Eeuo pipefail

# Usage:
#   ./opencode-setup.sh <vllm_base_url>
#
# Example:
#   ./opencode-setup.sh http://192.168.178.185:8000/v1
#
# Optional environment variables:
#   VLLM_API_KEY=your-key          # optional; default is empty = no Authorization header
#   VLLM_MODEL=exact/model/id      # optional; auto-detected from /v1/models if omitted
#   AUTO_INSTALL_OPENCODE=1        # set to 0 to disable auto-install

VLLM_BASE_URL="${1:?Usage: $0 <vllm_base_url>}"
VLLM_API_KEY="${VLLM_API_KEY:-}"
AUTO_INSTALL_OPENCODE="${AUTO_INSTALL_OPENCODE:-1}"
VLLM_MODEL="${VLLM_MODEL:-}"

# Global config path
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$XDG_CONFIG_HOME/opencode}"
OPENCODE_CONFIG_PATH="${OPENCODE_CONFIG_PATH:-$OPENCODE_CONFIG_DIR/opencode.json}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

json_escape() {
  python3 - <<'PY' "$1"
import json, sys
print(json.dumps(sys.argv[1]))
PY
}

validate_json_file() {
  python3 - "$1" 2>/dev/null <<'PY'
import json, sys
try:
    json.load(open(sys.argv[1]))
except (ValueError, IOError):
    sys.exit(1)
PY
}

echo "==> Checking prerequisites"
need_cmd curl
need_cmd python3

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found. Falling back to Python JSON parsing."
fi

VALID_URL="^[a-zA-Z][a-zA-Z0-9+.-]*://[a-zA-Z0-9.-]+\:[0-9]+$"
if ! echo "$VLLM_BASE_URL" | grep -qE "$VALID_URL"; then
  VALID_URL_NO_SCHEME="^[a-zA-Z0-9.-]+\:[0-9]+$"
  if echo "$VLLM_BASE_URL" | grep -qE "$VALID_URL_NO_SCHEME"; then
    VLLM_BASE_URL="http://$VLLM_BASE_URL"
  else
    echo "ERROR: invalid vLLM base URL format. Expected: <scheme>://host:port (e.g., http://localhost:8000/v1)" >&2
    exit 1
  fi
fi

# Strip trailing slash
VLLM_BASE_URL="${VLLM_BASE_URL%/}"

printf '%s\n' "==> Checking vLLM endpoint: ${VLLM_BASE_URL}/models"

CURL_ARGS=(-fsS)
if [[ -n "$VLLM_API_KEY" ]]; then
  CURL_ARGS+=(-H "Authorization: Bearer ${VLLM_API_KEY}")
fi

MODELS_JSON="$(curl "${CURL_ARGS[@]}" "${VLLM_BASE_URL}/models")" || {
  echo "ERROR: could not reach vLLM at ${VLLM_BASE_URL}/models" >&2
  echo "Check:"
  echo "  - vLLM is running"
  echo "  - base URL includes /v1"
  echo "  - scheme is included or can be inferred"
  echo "  - API key matches, if your server requires one"
  exit 1
}

if [[ -z "${VLLM_MODEL}" ]]; then
  if command -v jq >/dev/null 2>&1; then
    VLLM_MODEL="$(printf '%s' "$MODELS_JSON" | jq -r '.data[0].id // empty')"
  else
    VLLM_MODEL="$(python3 - <<'PY' "$MODELS_JSON"
import json, sys
doc = json.loads(sys.argv[1])
data = doc.get("data", [])
print(data[0]["id"] if data and "id" in data[0] else "")
PY
)"
  fi
fi

if [[ -z "${VLLM_MODEL}" ]]; then
  echo "ERROR: could not determine model name from vLLM /models response" >&2
  exit 1
fi

printf '%s\n' "==> Found model: ${VLLM_MODEL}"

mkdir -p "${OPENCODE_CONFIG_DIR}"

if [[ -f "${OPENCODE_CONFIG_PATH}" ]]; then
  BACKUP_PATH="${OPENCODE_CONFIG_PATH}.bak.$(date +%Y%m%d-%H%M%S)"
  cp "${OPENCODE_CONFIG_PATH}" "${BACKUP_PATH}"
  echo "==> Existing global config backed up to ${BACKUP_PATH}"
fi

VLLM_MODEL_ESCAPED="$(json_escape "${VLLM_MODEL}")"
BASE_URL_ESCAPED="$(json_escape "${VLLM_BASE_URL}")"

if [[ -n "${VLLM_API_KEY}" ]]; then
  API_KEY_LINE="\"apiKey\": $(json_escape "${VLLM_API_KEY}")"
else
  API_KEY_LINE="\"apiKey\": \"\""
fi

OPENCODE_CONFIG_DIR="$(cd "${OPENCODE_CONFIG_DIR}" 2>/dev/null && pwd)" || {
  echo "ERROR: config directory does not exist: ${OPENCODE_CONFIG_DIR}" >&2
  exit 1
}
umask 077
TEMP_CONFIG="$(mktemp "${OPENCODE_CONFIG_DIR}/.opencode_config.XXXXXX")" || {
  echo "ERROR: failed to create temp file" >&2
  exit 1
}
trap 'rm -f "$TEMP_CONFIG"' EXIT

cat > "${TEMP_CONFIG}" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "vllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "vLLM (local)",
      "options": {
        "baseURL": ${BASE_URL_ESCAPED},
        ${API_KEY_LINE}
      },
      "models": {
        ${VLLM_MODEL_ESCAPED}: {
          "name": ${VLLM_MODEL_ESCAPED}
        }
      }
    }
  },
  "model": "vllm/${VLLM_MODEL_ESCAPED}",
  "permission": {
    "bash": "ask",
    "edit": "allow",
    "webfetch": "allow"
  }
}
EOF

mv "${TEMP_CONFIG}" "${OPENCODE_CONFIG_PATH}"
trap - EXIT

if ! validate_json_file "${OPENCODE_CONFIG_PATH}"; then
  echo "ERROR: generated config is invalid JSON" >&2
  if [[ -f "${BACKUP_PATH}" ]]; then
    if validate_json_file "${BACKUP_PATH}"; then
      mv "${BACKUP_PATH}" "${OPENCODE_CONFIG_PATH}"
      echo "Restored backup to ${OPENCODE_CONFIG_PATH}" >&2
    else
      echo "Backup also invalid, removing corrupted file" >&2
      rm -f "${OPENCODE_CONFIG_PATH}" "${BACKUP_PATH}"
    fi
  fi
  exit 1
fi

echo "==> Wrote global OpenCode config to ${OPENCODE_CONFIG_PATH}"

if ! command -v opencode >/dev/null 2>&1; then
  if [[ "${AUTO_INSTALL_OPENCODE}" == "1" ]]; then
    echo "==> opencode not found, attempting install via npm"
    need_cmd npm
    npm install -g opencode-ai || {
      echo "ERROR: failed to install opencode-ai globally" >&2
      echo "Install it manually, then rerun this script."
      exit 1
    }
  else
    echo "ERROR: opencode is not installed" >&2
    echo "Install it first, or rerun with AUTO_INSTALL_OPENCODE=1"
    exit 1
  fi
fi

echo
printf '%s\n' "==> Launching OpenCode with model: vllm/${VLLM_MODEL}"
printf '%s\n' "==> Global config file: ${OPENCODE_CONFIG_PATH}"
if [[ -n "${VLLM_API_KEY}" ]]; then
  printf '%s\n' "==> Authorization header: enabled"
else
  printf '%s\n' "==> Authorization header: disabled"
fi
echo

exec opencode