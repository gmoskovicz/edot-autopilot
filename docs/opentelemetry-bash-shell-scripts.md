# OpenTelemetry for Bash / Shell Scripts — Complete Guide

> How to instrument Bash scripts — backups, ETL pipelines, deployment scripts, cron jobs — so they appear as real spans in Elastic APM.

## The problem

Shell scripts are the connective tissue of every production infrastructure. They run:

- **Nightly backups** that protect gigabytes of customer data
- **ETL pipelines** that load data warehouses before business hours
- **Deployment scripts** that push code to production
- **Cron jobs** that trigger invoicing, reporting, and expiry checks
- **Database maintenance** scripts that run VACUUM, ANALYZE, and index rebuilds
- **Certificate renewal** scripts (often a single cron entry in Let's Encrypt setups)

Every one of these is completely invisible to APM tools. There is no Bash OTel SDK. There is no shell agent. When a nightly backup silently fails or takes three times as long as usual, the team finds out when someone notices the restored data is stale — or when the backup disk is full.

The standard response is "add logging." But logs without trace context are noise. You can't correlate a slow backup with the disk IOPS spike that caused it. You can't track backup duration trends across 90 days. You can't set an SLO on "nightly backup completes within 2 hours."

With OpenTelemetry, you can do all of that — and it takes four lines of Bash.

## The solution: Telemetry Sidecar

The EDOT Autopilot telemetry sidecar runs as a local HTTP server on port 9411. Your Bash scripts send events to it using `curl` — which is available on essentially every Unix system ever built. The sidecar translates those events into OTLP spans and forwards them to Elastic.

Architecture:

```
[Bash Script / Cron Job]
    |
    | curl -X POST http://127.0.0.1:9411
    |
    v
[otel-sidecar.py :9411]   (Python, same host)
    |
    | OTLP/HTTP
    v
[Elastic Cloud APM]
```

The `|| true` at the end of the curl call ensures that if the sidecar is ever down, your script continues normally. Telemetry is always best-effort — it must never block the operation being observed.

## Step-by-step setup

### Step 1: Deploy the sidecar

```bash
git clone https://github.com/gmoskovicz/edot-autopilot
cd edot-autopilot
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

### Step 2: Configure and start the sidecar

```bash
export OTEL_SERVICE_NAME=backup-and-etl-scripts
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<your-base64-encoded-id:key>
export OTEL_DEPLOYMENT_ENVIRONMENT=production

# Start as background process (or use systemd — see below)
python otel-sidecar/otel-sidecar.py &
```

### Step 3: Add the helper function to your scripts

Paste the `otel_event` function at the top of each script you want to instrument, then call it at meaningful points.

### Step 4: Run and verify in Kibana

After running the script, navigate to Kibana → Observability → APM → Services within 60 seconds. Your service will appear.

## Code example

### The core helper function

```bash
#!/usr/bin/env bash
set -euo pipefail

# Telemetry helper — paste at the top of any script you want to observe
otel_event() {
  local name="$1"
  local attrs="${2:-{}}"
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true   # never block the script if sidecar is down
}
```

### Backup script

```bash
#!/usr/bin/env bash
set -euo pipefail

otel_event() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true
}

DB_NAME="${1:-myapp}"
BACKUP_DIR="/backups"
START_TIME=$(date +%s)

otel_event "backup.started" "{\"db.name\":\"$DB_NAME\"}"

pg_dump "$DB_NAME" | gzip > "$BACKUP_DIR/${DB_NAME}_$(date +%Y%m%d).sql.gz"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
SIZE_MB=$(du -m "$BACKUP_DIR/${DB_NAME}_$(date +%Y%m%d).sql.gz" | cut -f1)

otel_event "backup.complete" \
  "{\"db.name\":\"$DB_NAME\",\"duration_s\":$DURATION,\"size_mb\":$SIZE_MB,\"status\":\"ok\"}"
```

### ETL pipeline

```bash
#!/usr/bin/env bash
set -euo pipefail

otel_event() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true
}

PIPELINE_DATE="${1:-$(date +%Y-%m-%d)}"
SOURCE="legacy-erp"

otel_event "etl.extract.started" "{\"pipeline.date\":\"$PIPELINE_DATE\",\"source\":\"$SOURCE\"}"

# Extract phase
ROWS_EXTRACTED=$(extract_from_erp "$PIPELINE_DATE")
otel_event "etl.extract.complete" \
  "{\"pipeline.date\":\"$PIPELINE_DATE\",\"rows.extracted\":$ROWS_EXTRACTED,\"source\":\"$SOURCE\"}"

# Transform phase
otel_event "etl.transform.started" "{\"rows.input\":$ROWS_EXTRACTED}"
ROWS_TRANSFORMED=$(transform_data "$ROWS_EXTRACTED")
ROWS_REJECTED=$((ROWS_EXTRACTED - ROWS_TRANSFORMED))
otel_event "etl.transform.complete" \
  "{\"rows.output\":$ROWS_TRANSFORMED,\"rows.rejected\":$ROWS_REJECTED}"

# Load phase
otel_event "etl.load.started" "{\"rows.input\":$ROWS_TRANSFORMED}"
load_to_warehouse "$ROWS_TRANSFORMED"
otel_event "etl.load.complete" \
  "{\"rows.loaded\":$ROWS_TRANSFORMED,\"pipeline.date\":\"$PIPELINE_DATE\",\"status\":\"ok\"}"
```

### Deployment script

```bash
#!/usr/bin/env bash
set -euo pipefail

otel_event() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true
}

APP_NAME="${1:?Usage: deploy.sh <app-name> <version>}"
VERSION="${2:?}"
DEPLOY_ENV="${DEPLOY_ENV:-production}"
DEPLOYER="$(git config user.email 2>/dev/null || echo unknown)"

otel_event "deploy.started" \
  "{\"app.name\":\"$APP_NAME\",\"app.version\":\"$VERSION\",\"environment\":\"$DEPLOY_ENV\",\"deployer\":\"$DEPLOYER\"}"

START_TS=$(date +%s)

# ... actual deployment steps ...
docker pull "$APP_NAME:$VERSION"
docker stop "$APP_NAME-current" 2>/dev/null || true
docker run -d --name "$APP_NAME-current" "$APP_NAME:$VERSION"

DURATION=$(($(date +%s) - START_TS))

otel_event "deploy.complete" \
  "{\"app.name\":\"$APP_NAME\",\"app.version\":\"$VERSION\",\"environment\":\"$DEPLOY_ENV\",\"duration_s\":$DURATION,\"status\":\"ok\"}"
```

### Cron job with error handling

```bash
#!/usr/bin/env bash

otel_event() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true
}

# Trap errors and emit a failure event before exiting
trap 'otel_event "invoice.generation.failed" "{\"exit_code\":$?,\"line\":$LINENO}"' ERR

MONTH="${1:-$(date +%Y-%m)}"
COUNT=0

while IFS=, read -r customer_id email plan; do
    generate_invoice "$customer_id" "$MONTH"
    COUNT=$((COUNT + 1))
done < <(get_billable_customers)

otel_event "invoice.generation.complete" \
  "{\"month\":\"$MONTH\",\"invoices.generated\":$COUNT}"
```

### Using start_span / end_span for multi-step duration tracking

For scripts where you need accurate wall-clock duration per phase stored as proper span duration (rather than an attribute):

```bash
otel_start_span() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"start_span\",\"name\":\"$name\",\"attributes\":$attrs}" \
    2>/dev/null || echo ""
}

otel_end_span() {
  local span_response="$1"
  local error="${2:-}"
  local attrs="${3:-{}}"
  local span_id
  span_id=$(echo "$span_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('span_id',''))" 2>/dev/null || echo "")
  [ -z "$span_id" ] && return
  local error_field=""
  [ -n "$error" ] && error_field=",\"error\":\"$error\""
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"end_span\",\"span_id\":\"$span_id\"$error_field,\"attributes\":$attrs}" \
    >/dev/null || true
}

# Usage
SPAN=$(otel_start_span "db.vacuum" "{\"db.name\":\"myapp\"}")
vacuumdb --analyze myapp
otel_end_span "$SPAN" "" "{\"tables.analyzed\":42}"
```

### Running the sidecar as a systemd service

For cron-driven scripts, the sidecar needs to be always running — not just during the script:

```ini
# /etc/systemd/system/otel-sidecar.service
[Unit]
Description=OpenTelemetry Telemetry Sidecar
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/edot-autopilot/otel-sidecar/otel-sidecar.py
Environment=OTEL_SERVICE_NAME=backup-and-etl-scripts
Environment=ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
Environment=ELASTIC_API_KEY=<key>
Environment=OTEL_DEPLOYMENT_ENVIRONMENT=production
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable otel-sidecar
sudo systemctl start otel-sidecar
```

## What you'll see in Elastic

Once instrumented:

- **APM Services**: Your script group appears as a named service (e.g., `backup-and-etl-scripts`).
- **Operation trends**: Duration of `backup.complete`, `etl.load.complete`, and `deploy.complete` tracked over time. You can see immediately when a backup that normally takes 12 minutes starts taking 45.
- **Cron job history**: Every run of every cron job is recorded. You can query how many invoices were generated per month, or find the last time a backup was skipped.
- **SLO alerts**: Define an SLO that `backup.complete` must fire within a 2-hour window. Elastic alerts you if it does not.
- **Error tracking**: When a script hits the `ERR` trap, the failure event appears in the Errors tab with the exit code and line number.

Example ES|QL query to detect slow backups:

```esql
FROM traces-apm*
| WHERE service.name == "backup-and-etl-scripts"
  AND span.name == "backup.complete"
| EVAL duration_min = TO_DOUBLE(attributes.duration_s) / 60
| WHERE duration_min > 30
| KEEP @timestamp, attributes.db\.name, duration_min
| SORT @timestamp DESC
```

## Related

- [Telemetry Sidecar Pattern — full documentation](./telemetry-sidecar-pattern.md)
- [OpenTelemetry for Legacy Runtimes — overview](./opentelemetry-legacy-runtimes.md)
- [OpenTelemetry for PowerShell](./opentelemetry-powershell.md)
- [Business Span Enrichment](./business-span-enrichment.md)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other Bash/shell developers find this solution.
