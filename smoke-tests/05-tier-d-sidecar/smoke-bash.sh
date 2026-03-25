#!/usr/bin/env bash
# Smoke test: Tier D — Bash → OTEL Sidecar (traces + logs + metrics)
# Sends ETL spans, structured logs, and counters/histograms via curl to the sidecar.
# Run: OTEL_SIDECAR_URL=http://127.0.0.1:9411 bash smoke-bash.sh

set -euo pipefail
SIDECAR="${OTEL_SIDECAR_URL:-http://127.0.0.1:9411}"
SVC="smoke-tier-d-bash"

# ── Trace helpers ─────────────────────────────────────────────────────────────
otel_event() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true
}

otel_start() {
  local name="$1" attrs="${2:-{}}" traceparent="${3:-}"
  local body="{\"action\":\"start_span\",\"name\":\"$name\",\"attributes\":$attrs"
  [ -n "$traceparent" ] && body="$body,\"traceparent\":\"$traceparent\""
  body="$body}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "$body" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('span_id','') + '|' + d.get('traceparent',''))" 2>/dev/null || echo "|"
}

otel_end() {
  local span_id="$1" attrs="${2:-{}}" error="${3:-}"
  local body="{\"action\":\"end_span\",\"span_id\":\"$span_id\",\"attributes\":$attrs"
  [ -n "$error" ] && body="$body,\"error\":\"$error\""
  body="$body}"
  curl -sf -X POST "$SIDECAR" -H "Content-Type: application/json" -d "$body" >/dev/null || true
}

# ── Log helper ────────────────────────────────────────────────────────────────
otel_log() {
  local severity="${1:-INFO}" message="$2" attrs="${3:-{}}" traceparent="${4:-}"
  local body="{\"action\":\"log\",\"severity\":\"$severity\",\"body\":\"$message\",\"attributes\":$attrs"
  [ -n "$traceparent" ] && body="$body,\"traceparent\":\"$traceparent\""
  body="$body}"
  curl -sf -X POST "$SIDECAR" -H "Content-Type: application/json" -d "$body" >/dev/null || true
}

# ── Metric helpers ────────────────────────────────────────────────────────────
otel_counter() {
  local name="$1" value="${2:-1}" attrs="${3:-{}}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"metric_counter\",\"name\":\"$name\",\"value\":$value,\"attributes\":$attrs}" \
    >/dev/null || true
}

otel_histogram() {
  local name="$1" value="$2" attrs="${3:-{}}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"metric_histogram\",\"name\":\"$name\",\"value\":$value,\"attributes\":$attrs}" \
    >/dev/null || true
}

echo "[${SVC}] Sending Bash ETL spans + logs + metrics via sidecar at ${SIDECAR}..."

# ── ETL batch job — realistic Bash automation scenario ────────────────────────
START_MS=$(($(date +%s%N)/1000000))

RESULT=$(otel_start "etl.batch.run" \
  '{"batch.source":"legacy-erp","batch.schedule":"02:00 UTC","os":"linux","etl.type":"incremental"}')
BATCH_ID="${RESULT%%|*}"
BATCH_TP="${RESULT##*|}"

otel_log "INFO" "ETL batch started" \
  '{"batch.source":"legacy-erp","etl.type":"incremental"}' "$BATCH_TP"

sleep 0.1
otel_event "etl.extract.complete" \
  '{"extract.rows":42500,"extract.source":"oracle-erp","extract.duration_ms":820,"extract.tables":7}'
otel_log "INFO" "Extract complete: 42500 rows from oracle-erp" \
  '{"extract.rows":42500,"extract.source":"oracle-erp"}' "$BATCH_TP"
otel_counter "etl.rows.extracted" 42500 '{"source":"oracle-erp"}'

sleep 0.05
otel_event "etl.transform.complete" \
  '{"transform.rows_in":42500,"transform.rows_out":42483,"transform.errors":17,"transform.rules_applied":12}'
otel_log "WARN" "Transform completed with 17 errors" \
  '{"transform.errors":17,"transform.rows_in":42500}' "$BATCH_TP"
otel_counter "etl.transform.errors" 17 '{"source":"oracle-erp"}'

sleep 0.05
otel_event "etl.load.complete" \
  '{"load.rows":42483,"load.target":"bigquery","load.duration_ms":1200,"load.dataset":"analytics_prod"}'
otel_log "INFO" "Load complete: 42483 rows to bigquery" \
  '{"load.rows":42483,"load.target":"bigquery"}' "$BATCH_TP"
otel_counter "etl.rows.loaded" 42483 '{"target":"bigquery"}'

END_MS=$(($(date +%s%N)/1000000))
DURATION_MS=$((END_MS - START_MS))

otel_end "$BATCH_ID" \
  "{\"batch.total_rows\":42500,\"batch.errors\":17,\"batch.status\":\"success\",\"batch.duration_ms\":$DURATION_MS}"
otel_histogram "etl.batch.duration_ms" "$DURATION_MS" '{"batch.source":"oracle-erp","batch.status":"success"}'
otel_log "INFO" "ETL batch completed successfully" \
  "{\"batch.total_rows\":42500,\"batch.errors\":17,\"batch.duration_ms\":$DURATION_MS}" "$BATCH_TP"

echo "  ✅ etl.batch.run  rows=42500  errors=17  duration=${DURATION_MS}ms"

# ── Backup job ────────────────────────────────────────────────────────────────
RESULT=$(otel_start "backup.run" \
  '{"backup.type":"incremental","backup.target":"s3://backups","backup.retention_days":30}')
BACKUP_ID="${RESULT%%|*}"
BACKUP_TP="${RESULT##*|}"

otel_log "INFO" "Incremental backup started" \
  '{"backup.type":"incremental","backup.target":"s3://backups"}' "$BACKUP_TP"

sleep 0.05
otel_end "$BACKUP_ID" \
  '{"backup.size_mb":2048,"backup.files":18392,"backup.status":"ok","backup.compressed_mb":512}'
otel_histogram "backup.size_mb" 2048 '{"backup.type":"incremental","backup.target":"s3"}'
otel_counter "backup.runs.total" 1 '{"backup.type":"incremental","backup.status":"ok"}'
otel_log "INFO" "Backup completed: 2048MB, 18392 files" \
  '{"backup.size_mb":2048,"backup.files":18392}' "$BACKUP_TP"

echo "  ✅ backup.run  size=2048MB  files=18392"

echo "[${SVC}] Done → Kibana APM → ${SVC}"
