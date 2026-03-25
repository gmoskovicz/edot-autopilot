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

# ── Tier A: Java ──────────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier A: Java (native OTel SDK) ────────────────────────────${NC}"
run_test "08-tier-a-java" "python3 08-tier-a-java/smoke.py"

# ── Tier A: Go ────────────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier A: Go (native OTel SDK) ──────────────────────────────${NC}"
run_test "09-tier-a-go" "python3 09-tier-a-go/smoke.py"

# ── Tier A: Ruby ──────────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier A: Ruby (native OTel SDK) ────────────────────────────${NC}"
run_test "10-tier-a-ruby" "python3 10-tier-a-ruby/smoke.py"

# ── Tier A: .NET ──────────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier A: .NET C# (native OTel SDK) ─────────────────────────${NC}"
run_test "11-tier-a-dotnet" "python3 11-tier-a-dotnet/smoke.py"

# ── Tier A: PHP ───────────────────────────────────────────────────────────────
echo -e "${CYAN}── Tier A: PHP (native OTel SDK) ─────────────────────────────${NC}"
run_test "12-tier-a-php" "python3 12-tier-a-php/smoke.py"

# ── Tier B: Manual wrapping ───────────────────────────────────────────────────
echo -e "${CYAN}── Tier B: Manual handler wrapping ───────────────────────────${NC}"
run_test "03-tier-b-manual-wrap" "python3 03-tier-b-manual-wrap/smoke.py"
run_test "13-tier-b-django-orm"  "python3 13-tier-b-django-orm/smoke.py"
run_test "14-tier-b-flask-raw"   "python3 14-tier-b-flask-raw/smoke.py"
run_test "15-tier-b-tornado"     "python3 15-tier-b-tornado/smoke.py"
run_test "16-tier-b-bottle"      "python3 16-tier-b-bottle/smoke.py"
run_test "17-tier-b-falcon"      "python3 17-tier-b-falcon/smoke.py"
run_test "18-tier-b-aiohttp"     "python3 18-tier-b-aiohttp/smoke.py"
run_test "19-tier-b-celery"      "python3 19-tier-b-celery/smoke.py"

# ── Tier C: Monkey-patching ───────────────────────────────────────────────────
echo -e "${CYAN}── Tier C: Library monkey-patching ───────────────────────────${NC}"
run_test "04-tier-c-monkey-patch"     "python3 04-tier-c-monkey-patch/smoke.py"
run_test "20-tier-c-twilio"           "python3 20-tier-c-twilio/smoke.py"
run_test "21-tier-c-sendgrid"         "python3 21-tier-c-sendgrid/smoke.py"
run_test "22-tier-c-boto3-s3"         "python3 22-tier-c-boto3-s3/smoke.py"
run_test "23-tier-c-boto3-sqs"        "python3 23-tier-c-boto3-sqs/smoke.py"
run_test "24-tier-c-redis"            "python3 24-tier-c-redis/smoke.py"
run_test "25-tier-c-pymongo"          "python3 25-tier-c-pymongo/smoke.py"
run_test "26-tier-c-psycopg2"         "python3 26-tier-c-psycopg2/smoke.py"
run_test "27-tier-c-httpx"            "python3 27-tier-c-httpx/smoke.py"
run_test "28-tier-c-celery-worker"    "python3 28-tier-c-celery-worker/smoke.py"
run_test "29-tier-c-rabbitmq"         "python3 29-tier-c-rabbitmq/smoke.py"
run_test "30-tier-c-elasticsearch"    "python3 30-tier-c-elasticsearch/smoke.py"
run_test "31-tier-c-slack"            "python3 31-tier-c-slack/smoke.py"
run_test "32-tier-c-openai"           "python3 32-tier-c-openai/smoke.py"
run_test "51-tier-c-cuda-nvml"        "python3 51-tier-c-cuda-nvml/smoke.py"

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

# ── Tier D: Simulations (Python, always-run) ──────────────────────────────────
echo -e "${CYAN}── Tier D: Legacy runtime simulations ────────────────────────${NC}"
run_test "33-tier-d-cobol-batch"    "python3 33-tier-d-cobol-batch/smoke.py"
run_test "34-tier-d-powershell"     "python3 34-tier-d-powershell/smoke.py"
run_test "35-tier-d-sap-abap"       "python3 35-tier-d-sap-abap/smoke.py"
run_test "36-tier-d-ibm-rpg"        "python3 36-tier-d-ibm-rpg/smoke.py"
run_test "37-tier-d-classic-asp"    "python3 37-tier-d-classic-asp/smoke.py"
run_test "38-tier-d-vba-excel"      "python3 38-tier-d-vba-excel/smoke.py"
run_test "39-tier-d-matlab"         "python3 39-tier-d-matlab/smoke.py"
run_test "40-tier-d-r-statistical"  "python3 40-tier-d-r-statistical/smoke.py"
run_test "41-tier-d-lua"            "python3 41-tier-d-lua/smoke.py"
run_test "42-tier-d-tcl"            "python3 42-tier-d-tcl/smoke.py"
run_test "43-tier-d-awk-etl"        "python3 43-tier-d-awk-etl/smoke.py"
run_test "44-tier-d-fortran"        "python3 44-tier-d-fortran/smoke.py"
run_test "45-tier-d-delphi"         "python3 45-tier-d-delphi/smoke.py"
run_test "46-tier-d-coldfusion"     "python3 46-tier-d-coldfusion/smoke.py"
run_test "47-tier-d-julia"          "python3 47-tier-d-julia/smoke.py"
run_test "48-tier-d-nim"            "python3 48-tier-d-nim/smoke.py"
run_test "49-tier-d-ada"            "python3 49-tier-d-ada/smoke.py"
run_test "50-tier-d-zapier"         "python3 50-tier-d-zapier/smoke.py"
run_test "52-tier-d-dcgm-exporter"  "python3 52-tier-d-dcgm-exporter/smoke.py"

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

# ── Rich multi-service scenarios (service map + errors) ───────────────────────
echo -e "${CYAN}── Multi-Service Scenarios (complex architectures) ───────────${NC}"
run_test "60-ecommerce"           "python3 60-ecommerce/scenario.py"
run_test "61-auth-platform"       "python3 61-auth-platform/scenario.py"
run_test "62-data-pipeline"       "python3 62-data-pipeline/scenario.py"
run_test "63-ml-inference"        "python3 63-ml-inference/scenario.py"
run_test "64-saas-ops"            "python3 64-saas-ops/scenario.py"

# ── Mobile & Web Framework tests ──────────────────────────────────────────────
echo -e "${CYAN}── Mobile Platforms ─────────────────────────────────────────${NC}"
run_test "65-mobile-react-native"   "python3 65-mobile-react-native/smoke.py"
run_test "66-mobile-flutter"        "python3 66-mobile-flutter/smoke.py"
run_test "67-mobile-ios-swift"      "python3 67-mobile-ios-swift/smoke.py"
run_test "68-mobile-android-kotlin" "python3 68-mobile-android-kotlin/smoke.py"
run_test "69-mobile-xamarin-maui"   "python3 69-mobile-xamarin-maui/smoke.py"
run_test "70-mobile-ionic"          "python3 70-mobile-ionic/smoke.py"

echo -e "${CYAN}── Web Frontend / RUM ───────────────────────────────────────${NC}"
run_test "71-web-react-spa"         "python3 71-web-react-spa/smoke.py"
run_test "72-web-nextjs"            "python3 72-web-nextjs/smoke.py"
run_test "73-web-vue"               "python3 73-web-vue/smoke.py"
run_test "74-web-angular"           "python3 74-web-angular/smoke.py"
run_test "75-web-svelte"            "python3 75-web-svelte/smoke.py"

echo -e "${CYAN}── Backend Web Frameworks ───────────────────────────────────${NC}"
run_test "76-web-nestjs"            "python3 76-web-nestjs/smoke.py"
run_test "77-web-gin-go"            "python3 77-web-gin-go/smoke.py"
run_test "78-web-rails"             "python3 78-web-rails/smoke.py"
run_test "79-web-fastapi"           "python3 79-web-fastapi/smoke.py"
run_test "80-web-htmx"              "python3 80-web-htmx/smoke.py"

echo -e "${CYAN}── Mobile Multi-Service Scenario ────────────────────────────${NC}"
run_test "81-mobile-ecommerce"      "python3 81-mobile-ecommerce/scenario.py"

# ── E2E Auto-Instrumentation Verification ─────────────────────────────────────
echo -e "${CYAN}── E2E Auto-Instrumentation Verification ─────────────────${NC}"
echo -e "${CYAN}   (Tests that auto-instrumentation produces correct spans) ${NC}"
run_test "82-e2e-flask-ecommerce"   "python3 82-e2e-flask-ecommerce/smoke.py"
run_test "83-e2e-fastapi-ml"        "python3 83-e2e-fastapi-ml/smoke.py"
run_test "84-e2e-django-cms"        "python3 84-e2e-django-cms/smoke.py"

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
