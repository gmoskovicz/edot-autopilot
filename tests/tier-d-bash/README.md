# Tier D — Bash Scripts

Bash has no OpenTelemetry SDK. But Bash can `curl`. That's all we need.

## How it works

The `otel_event()`, `otel_start()`, and `otel_end()` functions are tiny curl wrappers that POST to the OTEL Sidecar. The sidecar translates these to OTLP spans sent to Elastic APM.

```bash
# Fire-and-forget
otel_event "backup.complete" '{"size_mb":2048,"duration_s":34,"status":"ok"}'

# Long-running span with start/end
SPAN=$(otel_start "etl.batch.run" '{"source":"legacy-erp"}')
# ... do the work ...
otel_end "$SPAN" '{"rows_processed":50000}'
```

Key design: `|| true` on every curl call ensures telemetry **never blocks the script**.

## Run

```bash
# 1. Start the sidecar first
cd ../../otel-sidecar
cp ../.env.example .env
# Edit .env with your credentials, then:
OTEL_SERVICE_NAME=bash-tier-d docker compose up -d

# 2. Run the demo
cd ../tests/tier-d-bash
bash demo.sh
```

## Verify in Elastic

Kibana → Observability → APM → Services → `bash-tier-d`

You'll see spans for `etl.batch.run`, `etl.extract.complete`, `etl.transform.complete`, `etl.load.complete`, and `backup.run` — each with business attributes you can alert on.
