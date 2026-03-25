#!/usr/bin/env bash
# Smoke test: Tier D — Bash → OTEL Sidecar
# Sends ETL spans via curl to the running sidecar.
# Run: OTEL_SIDECAR_URL=http://127.0.0.1:9411 bash smoke-bash.sh

set -euo pipefail
SIDECAR="${OTEL_SIDECAR_URL:-http://127.0.0.1:9411}"
SVC="smoke-tier-d-bash"

otel_event() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true
}

otel_start() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"start_span\",\"name\":\"$name\",\"attributes\":$attrs}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('span_id',''))" 2>/dev/null || echo ""
}

otel_end() {
  local span_id="$1" attrs="${2:-{}}" error="${3:-}"
  local body="{\"action\":\"end_span\",\"span_id\":\"$span_id\",\"attributes\":$attrs"
  [ -n "$error" ] && body="$body,\"error\":\"$error\""
  body="$body}"
  curl -sf -X POST "$SIDECAR" -H "Content-Type: application/json" -d "$body" >/dev/null || true
}

echo "[${SVC}] Sending Bash ETL spans via sidecar at ${SIDECAR}..."

# ETL batch job — realistic Bash automation scenario
BATCH=$(otel_start "etl.batch.run" \
  '{"batch.source":"legacy-erp","batch.schedule":"02:00 UTC","os":"linux"}')

sleep 0.1
otel_event "etl.extract.complete" '{"extract.rows":42500,"extract.source":"oracle-erp","extract.duration_ms":820}'
sleep 0.05
otel_event "etl.transform.complete" '{"transform.rows_in":42500,"transform.rows_out":42483,"transform.errors":17}'
sleep 0.05
otel_event "etl.load.complete" '{"load.rows":42483,"load.target":"bigquery","load.duration_ms":1200}'

otel_end "$BATCH" '{"batch.total_rows":42500,"batch.errors":17,"batch.status":"success","batch.duration_ms":2120}'
echo "  ✅ etl.batch.run  rows=42500  errors=17"

# Backup job
BACKUP=$(otel_start "backup.run" '{"backup.type":"incremental","backup.target":"s3://backups"}')
sleep 0.05
otel_end "$BACKUP" '{"backup.size_mb":2048,"backup.files":18392,"backup.status":"ok"}'
echo "  ✅ backup.run  size=2048MB"

echo "[${SVC}] Done → Kibana APM → ${SVC}"
