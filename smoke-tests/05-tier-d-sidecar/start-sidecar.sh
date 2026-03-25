#!/usr/bin/env bash
# Starts the OTEL sidecar in the background for Tier D smoke tests.
# Usage: source start-sidecar.sh    (to capture the PID)
#        bash start-sidecar.sh      (runs and stays in foreground if not sourced)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
SIDECAR_PY="${SCRIPT_DIR}/../../otel-sidecar/otel-sidecar.py"

# Load .env
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-smoke-tier-d-sidecar}"
export ELASTIC_OTLP_ENDPOINT
export ELASTIC_API_KEY
export OTEL_DEPLOYMENT_ENVIRONMENT="${OTEL_DEPLOYMENT_ENVIRONMENT:-smoke-test}"
export SIDECAR_PORT="${SIDECAR_PORT:-9411}"
export SIDECAR_HOST="127.0.0.1"

echo "[sidecar] Starting OTEL Sidecar on ${SIDECAR_HOST}:${SIDECAR_PORT}"
echo "[sidecar] Service: ${OTEL_SERVICE_NAME}"
echo "[sidecar] Endpoint: ${ELASTIC_OTLP_ENDPOINT}"

# Check if port already in use
if lsof -ti:${SIDECAR_PORT} >/dev/null 2>&1; then
  echo "[sidecar] Port ${SIDECAR_PORT} already in use — sidecar may already be running"
  export OTEL_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT}"
  return 0 2>/dev/null || exit 0
fi

python3 "$SIDECAR_PY" &
SIDECAR_PID=$!
export OTEL_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT}"

# Wait for it to be ready
for i in {1..10}; do
  sleep 0.3
  if curl -sf -X POST "${OTEL_SIDECAR_URL}" \
       -H "Content-Type: application/json" \
       -d '{"action":"health"}' >/dev/null 2>&1; then
    echo "[sidecar] Ready (PID=${SIDECAR_PID})"
    echo "[sidecar] Stop with: kill ${SIDECAR_PID}"
    export SIDECAR_PID
    return 0 2>/dev/null || true
    break
  fi
done
echo "[sidecar] Started (PID=${SIDECAR_PID}) — may still be initializing"
export SIDECAR_PID
