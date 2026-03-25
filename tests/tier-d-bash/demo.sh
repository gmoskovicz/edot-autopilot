#!/usr/bin/env bash
# Tier D — Bash scripts with OTEL Sidecar
#
# Bash has no OTel SDK. But bash can curl. That's all we need.
# The sidecar at localhost:9411 translates our JSON to OTLP spans.
#
# Usage: OTEL_SIDECAR_URL=http://localhost:9411 bash demo.sh
#        (or just bash demo.sh if sidecar is on default port)

set -euo pipefail

SIDECAR="${OTEL_SIDECAR_URL:-http://127.0.0.1:9411}"

# ── Helper: fire-and-forget event span ───────────────────────────────────────
otel_event() {
  local name="$1"
  local attrs="${2:-{}}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true   # never let telemetry block the script
}

# ── Helper: start a long-running span (returns span_id) ──────────────────────
otel_start() {
  local name="$1"
  local attrs="${2:-{}}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"start_span\",\"name\":\"$name\",\"attributes\":$attrs}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('span_id',''))" 2>/dev/null || echo ""
}

# ── Helper: end a long-running span ──────────────────────────────────────────
otel_end() {
  local span_id="$1"
  local attrs="${2:-{}}"
  local error="${3:-}"
  local body="{\"action\":\"end_span\",\"span_id\":\"$span_id\",\"attributes\":$attrs"
  [ -n "$error" ] && body="$body,\"error\":\"$error\""
  body="$body}"
  curl -sf -X POST "$SIDECAR" \
    -H "Content-Type: application/json" \
    -d "$body" >/dev/null || true
}

# ─────────────────────────────────────────────────────────────────────────────
# Simulated ETL batch job — the kind that runs on a server at 2am
# and nobody knows what happened if it fails.
# ─────────────────────────────────────────────────────────────────────────────

echo "Starting ETL batch job..."

BATCH_SPAN=$(otel_start "etl.batch.run" \
  '{"batch.source":"legacy-erp","batch.schedule":"02:00 UTC","environment":"production"}')

START=$(date +%s)

# Step 1: Extract
echo "  Extracting from legacy ERP..."
sleep 0.5
ROW_COUNT=$((RANDOM % 50000 + 10000))
otel_event "etl.extract.complete" \
  "{\"extract.rows\":$ROW_COUNT,\"extract.source\":\"oracle-erp\",\"extract.duration_ms\":500}"

# Step 2: Transform
echo "  Transforming $ROW_COUNT rows..."
sleep 0.3
ERRORS=$((RANDOM % 20))
otel_event "etl.transform.complete" \
  "{\"transform.rows_in\":$ROW_COUNT,\"transform.rows_out\":$((ROW_COUNT-ERRORS)),\"transform.errors\":$ERRORS}"

# Step 3: Load
echo "  Loading to data warehouse..."
sleep 0.4
otel_event "etl.load.complete" \
  "{\"load.rows\":$((ROW_COUNT-ERRORS)),\"load.target\":\"bigquery\",\"load.duration_ms\":400}"

DURATION=$(( ($(date +%s) - START) * 1000 ))

# End the parent span with summary
otel_end "$BATCH_SPAN" \
  "{\"batch.total_rows\":$ROW_COUNT,\"batch.errors\":$ERRORS,\"batch.duration_ms\":$DURATION,\"batch.status\":\"success\"}"

echo "ETL complete. $ROW_COUNT rows processed, $ERRORS errors. Check Kibana APM."

# ─────────────────────────────────────────────────────────────────────────────
# Simulated backup script
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Running backup..."

BACKUP_SPAN=$(otel_start "backup.run" \
  '{"backup.type":"incremental","backup.target":"s3://company-backups"}')

sleep 0.2
SIZE_MB=$((RANDOM % 2048 + 512))

otel_end "$BACKUP_SPAN" \
  "{\"backup.size_mb\":$SIZE_MB,\"backup.files\":$((RANDOM % 10000)),\"backup.status\":\"ok\"}"

echo "Backup complete. ${SIZE_MB}MB. Check Kibana APM."
