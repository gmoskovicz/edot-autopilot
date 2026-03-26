#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EDOT Autopilot — Real SDK Integration Tests
#
# Spins up real Java / Node.js / Python processes against a local OTel Collector
# (file exporter). No Elastic credentials required.
#
# Usage:
#   bash tests/integration/run.sh
#
# Prerequisites:
#   docker (with compose plugin)
#   python3
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✅ $*${NC}"; }
fail() { echo -e "  ${RED}❌ $*${NC}"; }
info() { echo -e "  ${CYAN}ℹ  $*${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️  $*${NC}"; }

echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  EDOT Autopilot — Real SDK Integration Tests${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""

cleanup() {
  info "Tearing down Docker stack..."
  docker compose down --volumes --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# ── Prepare output directory ──────────────────────────────────────────────────
mkdir -p output
chmod 777 output  # collector container user must be able to write here
rm -f output/traces.jsonl output/metrics.jsonl output/logs.jsonl

# ── Build and start the stack ─────────────────────────────────────────────────
info "Building images (Java build may take ~2 minutes on first run)..."
docker compose build 2>&1 | grep -E "^(#|=>|\[|DONE|ERROR)" | tail -20 || true
echo ""

info "Starting OTel Collector + all SDK services..."
docker compose up -d
sleep 5  # give the collector time to bind ports before health checks begin

# ── Wait for all services to be healthy ───────────────────────────────────────
wait_healthy() {
  local service="$1" url="$2" label="$3" retries="${4:-24}"
  info "Waiting for $label to be ready..."
  for i in $(seq 1 "$retries"); do
    if curl -sf "$url" >/dev/null 2>&1; then
      ok "$label ready"
      return 0
    fi
    sleep 3
  done
  fail "$label did not become healthy after $((retries * 3))s"
  docker compose logs "$service" | tail -20
  return 1
}

wait_healthy "tier-a-python" "http://localhost:8000/health"        "FastAPI (Python)"   16
wait_healthy "tier-a-nodejs" "http://localhost:3001/health"        "Express (Node.js)"  16
wait_healthy "tier-a-java"   "http://localhost:8080/actuator/health" "Spring Boot (Java)" 50
echo ""

# ── Exercise each service to generate spans ───────────────────────────────────
info "Generating traffic against each service..."

echo ""
echo -e "${CYAN}── FastAPI (Python) ──────────────────────────────────────────${NC}"
curl -sf "http://localhost:8000/health"    >/dev/null && ok "GET /health"
curl -sf "http://localhost:8000/products"  >/dev/null && ok "GET /products" || warn "GET /products — endpoint may differ"
curl -sf -X POST "http://localhost:8000/checkout" \
     -H "Content-Type: application/json" \
     -d '{"product_id":1,"quantity":2,"customer_id":"ci-test","customer_tier":"enterprise"}' \
     >/dev/null 2>&1 && ok "POST /checkout" || warn "POST /checkout — endpoint may differ"

echo ""
echo -e "${CYAN}── Express (Node.js) ─────────────────────────────────────────${NC}"
curl -sf "http://localhost:3001/health"   >/dev/null && ok "GET /health"
curl -sf "http://localhost:3001/orders"   >/dev/null && ok "GET /orders" || warn "GET /orders — endpoint may differ"
curl -sf -X POST "http://localhost:3001/orders" \
     -H "Content-Type: application/json" \
     -d '{"item":"widget","quantity":5,"customer_id":"ci-test"}' \
     >/dev/null 2>&1 && ok "POST /orders" || warn "POST /orders — endpoint may differ"

echo ""
echo -e "${CYAN}── Spring Boot (Java) ────────────────────────────────────────${NC}"
curl -sf "http://localhost:8080/actuator/health" >/dev/null && ok "GET /actuator/health"
curl -sf "http://localhost:8080/orders"          >/dev/null && ok "GET /orders" || warn "GET /orders — endpoint may differ"
curl -sf -X POST "http://localhost:8080/orders" \
     -H "Content-Type: application/json" \
     -d '{"item":"widget","quantity":3,"customerId":"ci-test"}' \
     >/dev/null 2>&1 && ok "POST /orders" || warn "POST /orders — endpoint may differ"

# ── Wait for OTel Collector to flush ─────────────────────────────────────────
echo ""
info "Waiting for OTel Collector batch export (5s)..."
sleep 5

# Force-stop apps so collector flushes remaining spans
docker compose stop tier-a-python tier-a-nodejs tier-a-java 2>/dev/null || true
sleep 3

# ── Validate collector output ─────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Validating spans ──────────────────────────────────────────${NC}"

TRACES_FILE="output/traces.jsonl"
if [ ! -f "$TRACES_FILE" ] || [ ! -s "$TRACES_FILE" ]; then
  fail "No traces.jsonl produced — collector received no spans"
  echo ""
  echo "  Collector logs:"
  docker compose logs collector | tail -30
  exit 1
fi

SPAN_LINES=$(wc -l < "$TRACES_FILE")
info "Collector wrote $SPAN_LINES trace batch(es) to $TRACES_FILE"

python3 validate.py --traces "$TRACES_FILE"

echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Integration tests passed${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""
