#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EDOT Autopilot — Python smoke test runner (used inside Docker runner container)
#
# Runs all smoke.py tests in order, prints pass/fail per test, exits non-zero
# if any test failed.  Designed to be executed inside a container where:
#   - Python 3 + OTel packages are pre-installed
#   - ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY are set as env vars
#
# Usage:
#   bash runner.sh              # run all tests
#   bash runner.sh tier-a       # run only tests matching "tier-a"
#   bash runner.sh 30 40        # run tests 30-40
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

FILTER="${1:-}"
PASS=0; FAIL=0; SKIP=0
FAILED_TESTS=()

# Collect all smoke.py files in numeric order
ALL_TESTS=($(ls -d [0-9][0-9]-*/smoke.py 2>/dev/null | sort))

echo ""
echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${CYAN}  EDOT Autopilot — Full Smoke Test Suite                            ${NC}"
echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════════════${NC}"
echo -e "  Endpoint:  ${ELASTIC_OTLP_ENDPOINT:-NOT SET}"
echo -e "  Tests:     ${#ALL_TESTS[@]} smoke.py files found"
echo -e "  Filter:    ${FILTER:-none}"
echo ""

if [ -z "${ELASTIC_OTLP_ENDPOINT:-}" ] || [ -z "${ELASTIC_API_KEY:-}" ]; then
  echo -e "${RED}  ❌ ELASTIC_OTLP_ENDPOINT or ELASTIC_API_KEY not set${NC}"
  echo -e "     Copy .env.example → .env and fill in your Elastic Cloud credentials"
  exit 1
fi

run_test() {
  local smoke_file="$1"
  local dir
  dir=$(dirname "$smoke_file")
  local name="${dir##*/}"

  # Apply filter if set
  if [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]]; then
    SKIP=$((SKIP+1))
    return
  fi

  # Tier section header
  local tier
  case "$name" in
    0[12]-*|08-*|09-*|1[012]-*) tier="Tier A — Native OTel SDK" ;;
    0[3]-*|1[3-9]-*)             tier="Tier B — Manual wrapping" ;;
    0[4]-*|2[0-9]-*|3[012]-*)   tier="Tier C — Monkey-patching" ;;
    0[5]-*|3[3-9]-*|4[0-9]-*|50-*) tier="Tier D — Sidecar simulation" ;;
    07-*)                         tier="Cross-tier end-to-end" ;;
    *)                            tier="Other" ;;
  esac

  echo -e "${CYAN}  ▶ ${name}${NC}  ${YELLOW}[${tier}]${NC}"

  local output
  if output=$(python3 "$smoke_file" 2>&1); then
    echo "$output" | grep -v "NotOpenSSLWarning\|warnings.warn\|DeprecationWarning" | sed 's/^/    /'
    echo -e "  ${GREEN}✅ PASS${NC}  $name"
    PASS=$((PASS+1))
  else
    echo "$output" | sed 's/^/    /'
    echo -e "  ${RED}❌ FAIL${NC}  $name"
    FAIL=$((FAIL+1))
    FAILED_TESTS+=("$name")
  fi
  echo ""
}

CURRENT_TIER=""
for smoke_file in "${ALL_TESTS[@]}"; do
  run_test "$smoke_file"
done

# ── Summary ──────────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════════════${NC}"
TOTAL=$((PASS+FAIL))
echo -e "  Results:  ${GREEN}${PASS} passed${NC}  ${RED}${FAIL} failed${NC}  ${YELLOW}${SKIP} skipped${NC}  (${TOTAL} ran)"

if [ ${#FAILED_TESTS[@]} -gt 0 ]; then
  echo -e "\n  ${RED}Failed tests:${NC}"
  for t in "${FAILED_TESTS[@]}"; do
    echo -e "    ${RED}• $t${NC}"
  done
fi

echo ""
echo -e "  Kibana APM:  Observability → APM → Services  (filter: service.name: smoke-*)"
echo -e "  ES|QL:       FROM traces-apm* | WHERE service.name LIKE \"smoke*\" | SORT @timestamp DESC | LIMIT 20"
echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════════════${NC}"
echo ""

if [ $FAIL -gt 0 ]; then exit 1; fi
