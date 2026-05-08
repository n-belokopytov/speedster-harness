#!/usr/bin/env bash
set -euo pipefail

# Simple setup wrapper: configure all roles to use the same model endpoint
# and auto-detect the first available model.
#
# Usage:
#   ./setup-simple.sh [endpoint_url]
#
# Default URL: localhost:8000
#
# Optional env vars:
#   API_KEY     API key for the model endpoint (default: empty)
#   MODEL       Override auto-detected model
#

URL="${1:-localhost:8000}"
API_KEY="${API_KEY:-}"
MODEL="${MODEL:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Normalize URL: strip trailing slash, prepend http:// if no scheme
URL="${URL%/}"
[[ ! "$URL" =~ ^https?:// ]] && URL="http://$URL"

echo "==> Model endpoint: ${URL}"

# Check prerequisites
for cmd in curl python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: '$cmd' is required but not found" >&2
    exit 1
  fi
done

# Build curl arguments
CURL_ARGS=(-fsS)
if [[ -n "$API_KEY" ]]; then
  CURL_ARGS+=(-H "Authorization: Bearer ${API_KEY}")
fi

# Fetch available models
echo "==> Fetching models from ${URL}/models ..."
MODELS_JSON="$(curl "${CURL_ARGS[@]}" "${URL}/models")" || {
  echo "ERROR: could not reach endpoint at ${URL}/models" >&2
  echo "Check: the model server is running and the URL is correct" >&2
  exit 1
}

# Auto-detect first model if not specified
if [[ -z "$MODEL" ]]; then
  MODEL="$(python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0]['id'])" <<< "$MODELS_JSON")"
fi

if [[ -z "$MODEL" ]]; then
  echo "ERROR: could not determine model name" >&2
  exit 1
fi

echo "==> Model: ${MODEL}"

# Run setup with pre-filled parameters
echo "==> Running setup.sh ..."
API_KEY="$API_KEY" MODEL="$MODEL" bash "${SCRIPT_DIR}/setup.sh" --url "$URL"
