#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EDOT Autopilot — Full smoke test suite
#
# Runs all tier tests in order, then verifies spans reached Elastic.
#
# Usage:
#   cd smoke-tests
#   bash run-all.sh
#
# Prerequisites:
#   pip3 install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
#   npm install (in 02-tier-a-nodejs/ for Node.js test)
#   perl modules: LWP::UserAgent JSON  (for Perl test)
#
# Optional:
#   Set ELASTIC_ES_READ_API_KEY in .env to enable ES content verification.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✅ $*${NC}"; }
fail() { echo -e "  ${RED}❌ $*${NC}"; }
info() { echo -e "  ${CYAN}ℹ  $*${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️  $*${NC}"; }

SIDECAR_PID=""

cleanup() {
  if [ -n "$SIDECAR_PID" ] && kill -0 "$SIDECAR_PID" 2>/dev/null; then
    info "Stopping sidecar (PID=$SIDECAR_PID)..."
    kill "$SIDECAR_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  EDOT Autopilot — Smoke Test Suite${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""

# ── Check .env ────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  fail ".env not found — copy .env.example and fill in your credentials"
  exit 1
fi
set -a && source .env && set +a

if [ -z "${ELASTIC_OTLP_ENDPOINT:-}" ] || [ -z "${ELASTIC_API_KEY:-}" ]; then
  fail "ELASTIC_OTLP_ENDPOINT or ELASTIC_API_KEY not set in .env"
  exit 1
fi
info "OTLP endpoint: ${ELASTIC_OTLP_ENDPOINT}"
echo ""

PASS=0; FAIL=0

run_test() {
  local name="$1" cmd="$2"
  echo -e "  ${CYAN}▶ ${name}${NC}"
  if eval "$cmd" 2>&1 | grep -v NotOpenSSLWarning | grep -v "warnings.warn" | \
       sed 's/^/    /'; then
    ok "$name passed"
    PASS=$((PASS+1))
  else
    fail "$name failed"
    FAIL=$((FAIL+1))
  fi
  echo ""
}

# ── Tier A: Python ────────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier A: Python (native OTel SDK) ──────────────────────────${NC}"
run_test "01-tier-a-python" "python3 01-tier-a-python/smoke.py"

# ── Tier A: Node.js ───────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier A: Node.js (native OTel SDK) ─────────────────────────${NC}"
if command -v node >/dev/null 2>&1; then
  if [ ! -d "02-tier-a-nodejs/node_modules" ]; then
    info "Installing Node.js dependencies..."
    (cd 02-tier-a-nodejs && npm install --silent 2>/dev/null)
  fi
  run_test "02-tier-a-nodejs" "node 02-tier-a-nodejs/smoke.js"
else
  warn "Node.js not found — skipping 02-tier-a-nodejs"
fi

# ── Tier B: Manual wrapping ───────────────────────────────────────────────────
echo -e "${CYAN}── Tier B: Manual handler wrapping ───────────────────────────${NC}"
run_test "03-tier-b-manual-wrap" "python3 03-tier-b-manual-wrap/smoke.py"

# ── Tier C: Monkey-patching ───────────────────────────────────────────────────
echo -e "${CYAN}── Tier C: Library monkey-patching ───────────────────────────${NC}"
run_test "04-tier-c-monkey-patch" "python3 04-tier-c-monkey-patch/smoke.py"

# ── Tier D: Sidecar ───────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier D: Sidecar (legacy languages) ────────────────────────${NC}"

# Start sidecar
SIDECAR_SCRIPT="$(pwd)/../otel-sidecar/otel-sidecar.py"
if [ ! -f "$SIDECAR_SCRIPT" ]; then
  warn "otel-sidecar.py not found at $SIDECAR_SCRIPT — skipping Tier D tests"
else
  export OTEL_SERVICE_NAME="smoke-tier-d-sidecar"
  info "Starting OTEL Sidecar..."
  python3 "$SIDECAR_SCRIPT" &
  SIDECAR_PID=$!

  # Wait for sidecar to be ready
  for i in {1..10}; do
    sleep 0.3
    if curl -sf -X POST "http://127.0.0.1:${SIDECAR_PORT:-9411}" \
         -H "Content-Type: application/json" \
         -d '{"action":"health"}' >/dev/null 2>&1; then
      ok "Sidecar ready (PID=$SIDECAR_PID)"
      break
    fi
    if [ $i -eq 10 ]; then
      fail "Sidecar failed to start"; FAIL=$((FAIL+1))
    fi
  done
  echo ""

  export OTEL_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT:-9411}"

  # Python sidecar client
  run_test "05-tier-d-sidecar (python client)" \
    "python3 05-tier-d-sidecar/smoke-python.py"

  # Bash
  run_test "05-tier-d-sidecar (bash)" \
    "bash 05-tier-d-sidecar/smoke-bash.sh"

  # Perl
  if perl -e 'use LWP::UserAgent; use JSON' 2>/dev/null; then
    run_test "05-tier-d-sidecar (perl)" \
      "perl 05-tier-d-sidecar/smoke-perl.pl"
  else
    warn "Perl LWP::UserAgent or JSON not installed — skipping Perl test"
    info "Install with: cpan install LWP::UserAgent JSON"
  fi
fi

# ── Cross-tier full O11y scenario ─────────────────────────────────────────────
echo -e "${CYAN}── Cross-Tier: Full O11y End-to-End Scenario ─────────────────${NC}"

SCENARIO_SCRIPT="$(pwd)/07-cross-tier-full-o11y/scenario.py"
if [ ! -f "$SCENARIO_SCRIPT" ]; then
  warn "07-cross-tier-full-o11y/scenario.py not found — skipping"
else
  if [ -n "$SIDECAR_PID" ] && kill -0 "$SIDECAR_PID" 2>/dev/null; then
    # Sidecar is running — set its service name to the cross-tier Tier D service
    info "Restarting sidecar with service name: notification-sms-bash"
    kill "$SIDECAR_PID" 2>/dev/null || true
    sleep 0.3
    export OTEL_SERVICE_NAME="notification-sms-bash"
    python3 "$SIDECAR_SCRIPT" &
    SIDECAR_PID=$!
    for i in {1..10}; do
      sleep 0.3
      if curl -sf -X POST "http://127.0.0.1:${SIDECAR_PORT:-9411}" \
           -H "Content-Type: application/json" \
           -d '{"action":"health"}' >/dev/null 2>&1; then
        break
      fi
    done
    export OTEL_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT:-9411}"
    run_test "07-cross-tier-full-o11y" "python3 $SCENARIO_SCRIPT"
  else
    warn "Sidecar not running — starting it for cross-tier Tier D"
    export OTEL_SERVICE_NAME="notification-sms-bash"
    python3 "$SIDECAR_SCRIPT" &
    SIDECAR_PID=$!
    for i in {1..10}; do
      sleep 0.3
      if curl -sf -X POST "http://127.0.0.1:${SIDECAR_PORT:-9411}" \
           -H "Content-Type: application/json" \
           -d '{"action":"health"}' >/dev/null 2>&1; then
        ok "Sidecar ready for cross-tier scenario"
        break
      fi
    done
    export OTEL_SIDECAR_URL="http://127.0.0.1:${SIDECAR_PORT:-9411}"
    run_test "07-cross-tier-full-o11y" "python3 $SCENARIO_SCRIPT"
  fi
fi

# ── Verify ────────────────────────────────────────────────────────────────────
echo -e "${CYAN}── Verification ──────────────────────────────────────────────${NC}"
python3 06-verify/check_spans.py 2>&1 | grep -v NotOpenSSLWarning | grep -v "warnings.warn"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
TOTAL=$((PASS+FAIL))
if [ $FAIL -eq 0 ]; then
  echo -e "${GREEN}  ✅ All ${TOTAL} tests passed${NC}"
else
  echo -e "${RED}  ❌ ${FAIL}/${TOTAL} tests failed${NC}"
fi
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""
