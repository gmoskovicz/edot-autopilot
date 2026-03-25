# OTEL Sidecar — Universal Telemetry Bridge

A tiny HTTP server that translates simple JSON payloads into OTLP spans sent to Elastic APM.

Any process that can make an HTTP POST — COBOL, Perl, Bash, PowerShell, SAP ABAP, IBM RPG, Classic ASP, Flutter — can now emit traces to Elastic.

## How it works

```
[legacy process] --HTTP POST--> [sidecar:9411] --OTLP/HTTP--> [Elastic Cloud]
```

The legacy process never touches OpenTelemetry directly. It just POSTs JSON to localhost.

## API

### Fire-and-forget event
```bash
curl -X POST http://localhost:9411 \
  -H "Content-Type: application/json" \
  -d '{"action":"event","name":"order.processed","attributes":{"order.id":"123","amount":4200}}'
```

### Multi-step span (start → work → end)
```bash
# Start
RESP=$(curl -s -X POST http://localhost:9411 \
  -H "Content-Type: application/json" \
  -d '{"action":"start_span","name":"batch.etl","attributes":{"source":"legacy-erp"}}')
SPAN_ID=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['span_id'])")

# ... do your work ...

# End (with extra attributes collected during execution)
curl -X POST http://localhost:9411 \
  -H "Content-Type: application/json" \
  -d "{\"action\":\"end_span\",\"span_id\":\"$SPAN_ID\",\"attributes\":{\"rows.processed\":50000}}"
```

### Health check
```bash
curl http://localhost:9411 -d '{"action":"health"}'
# → {"ok": true, "spans_active": 0}
```

## Setup

### With Docker Compose
```bash
cp ../.env.example .env
# edit .env with your Elastic credentials
docker compose up -d
```

### Bare metal (systemd)
```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

export OTEL_SERVICE_NAME=my-legacy-service
export ELASTIC_OTLP_ENDPOINT=https://xxx.ingest.us-central1.gcp.elastic.cloud:443
export ELASTIC_API_KEY=your-api-key

python otel-sidecar.py
```

### As a systemd service
```ini
[Unit]
Description=OTEL Sidecar
After=network.target

[Service]
Type=simple
User=sidecar
EnvironmentFile=/etc/otel-sidecar.env
ExecStart=/usr/bin/python3 /opt/otel-sidecar/otel-sidecar.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Distributed trace propagation

The sidecar supports W3C `traceparent` headers for connecting spans across service boundaries:

```bash
# Span started by another service propagates its traceparent here
curl -X POST http://localhost:9411 \
  -d '{"action":"start_span","name":"legacy.step","traceparent":"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}'
```
