# Telemetry Sidecar Pattern — Complete Guide

> Architecture, deployment, and reference documentation for the EDOT Autopilot telemetry sidecar — the universal bridge between legacy runtimes and Elastic APM.

## What the telemetry sidecar pattern is

The telemetry sidecar pattern solves a specific problem: how do you instrument a process that runs in a language or runtime for which no OpenTelemetry SDK exists?

The answer is: you don't instrument it directly. You run a small, purpose-built HTTP server on the same host. The legacy process calls that server with simple HTTP POST requests. The server — the sidecar — handles all the OpenTelemetry complexity: span creation, trace context propagation, OTLP protocol, and export to Elastic.

The legacy process only needs to be able to make an HTTP POST call. Every runtime that has ever existed can do that — COBOL via `CALL "SYSTEM"` with curl, Perl via `LWP::UserAgent`, Classic ASP via `MSXML2.ServerXMLHTTP`, PowerShell via `Invoke-RestMethod`, Bash via `curl`. The sidecar speaks to all of them with a single JSON API.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Host (or Docker network)                                            │
│                                                                      │
│  ┌─────────────────────┐     HTTP POST      ┌─────────────────────┐ │
│  │   Legacy Process    │ ─────────────────> │  otel-sidecar.py    │ │
│  │                     │  127.0.0.1:9411    │  (Python 3)         │ │
│  │  COBOL / Perl /     │  JSON payload      │                     │ │
│  │  Classic ASP /      │                    │  Receives events,   │ │
│  │  PowerShell /       │ <──────────────── │  creates OTLP spans,│ │
│  │  Bash / Python 2    │  {"ok": true}      │  manages trace ctx  │ │
│  └─────────────────────┘  or span_id        └──────────┬──────────┘ │
│                                                         │            │
└─────────────────────────────────────────────────────────┼────────────┘
                                                          │
                                              OTLP/HTTP (port 443)
                                                          │
                                                          ▼
                                             ┌─────────────────────────┐
                                             │   Elastic Cloud APM     │
                                             │                         │
                                             │   Kibana APM Services,  │
                                             │   Trace Explorer,       │
                                             │   Service Map,          │
                                             │   Anomaly Detection     │
                                             └─────────────────────────┘
```

The sidecar binds only to `127.0.0.1` — it is not reachable from outside the host. In Docker, the sidecar container uses `network_mode: "service:<app>"` to share the app container's network namespace, making `127.0.0.1:9411` reachable from the app container.

## The 3 supported actions

The sidecar HTTP API accepts POST requests to `/` with a JSON body containing an `action` field.

### Action: `event`

Emit a single, point-in-time span. The span starts and ends immediately when the sidecar receives the request.

```json
{
  "action": "event",
  "name": "invoice.sent",
  "attributes": {
    "invoice.id": "INV-001",
    "invoice.amount": 4500,
    "customer.id": "cust_abc123"
  }
}
```

Optional `error` field marks the span as an error:

```json
{
  "action": "event",
  "name": "payment.failed",
  "error": "card declined",
  "attributes": {
    "payment.decline_code": "insufficient_funds",
    "customer.id": "cust_abc123"
  }
}
```

Response: `{"ok": true}`

Use `event` when:
- The operation completes before you can call the sidecar (batch record processed, file written, email sent)
- Duration is not meaningful or is captured in an attribute
- You want the simplest possible integration

### Action: `start_span`

Begin a span. Returns a `span_id` that you use later to end the span. The sidecar measures wall-clock duration from `start_span` to `end_span` and records it as the span duration in Elastic.

```json
{
  "action": "start_span",
  "name": "reconciliation.run",
  "attributes": {
    "account.id": "ACC-9921",
    "trade.date": "2026-03-25"
  }
}
```

Response:

```json
{
  "span_id": "a3f1c8b2-7e44-4d9a-b21e-3c8f9a0d1e5b",
  "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-a3f1c8b2abcdef01-01"
}
```

The `traceparent` value can be propagated to downstream services if you want distributed trace context to flow across service boundaries.

Use `start_span` / `end_span` when:
- Duration matters and you want accurate wall-clock measurement
- You have a multi-phase operation (extract → transform → load) and want each phase timed

### Action: `end_span`

End a previously started span. Optionally add final attributes and mark the span as an error.

```json
{
  "action": "end_span",
  "span_id": "a3f1c8b2-7e44-4d9a-b21e-3c8f9a0d1e5b",
  "attributes": {
    "records.matched":   98234,
    "records.unmatched": 12,
    "reconciliation.status": "exceptions"
  }
}
```

With an error:

```json
{
  "action": "end_span",
  "span_id": "a3f1c8b2-7e44-4d9a-b21e-3c8f9a0d1e5b",
  "error": "DB connection pool exhausted after 3 retries",
  "attributes": {
    "retry.attempts": 3,
    "error.category": "upstream"
  }
}
```

Response: `{"ok": true}`

## Deployment options

### Option 1: Docker (recommended for containerized apps)

Use `network_mode: "service:<app>"` to share the network namespace. This makes `127.0.0.1:9411` available inside the app container.

```yaml
# docker-compose.yml
services:
  legacy-app:
    image: your-legacy-image
    depends_on: [otel-sidecar]
    environment:
      # app-specific env vars

  otel-sidecar:
    build:
      context: .
      dockerfile: otel-sidecar/Dockerfile.sidecar
    network_mode: "service:legacy-app"   # shares legacy-app's network namespace
    environment:
      OTEL_SERVICE_NAME:           ${OTEL_SERVICE_NAME:-legacy-service}
      ELASTIC_OTLP_ENDPOINT:       ${ELASTIC_OTLP_ENDPOINT}
      ELASTIC_API_KEY:             ${ELASTIC_API_KEY}
      OTEL_DEPLOYMENT_ENVIRONMENT: ${OTEL_DEPLOYMENT_ENVIRONMENT:-production}
      SIDECAR_PORT:                9411
    restart: unless-stopped
```

```dockerfile
# otel-sidecar/Dockerfile.sidecar
FROM python:3.12-slim
RUN pip install --no-cache-dir \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-http
COPY otel-sidecar.py /
CMD ["python", "/otel-sidecar.py"]
```

Start:

```bash
OTEL_SERVICE_NAME=my-service \
ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io \
ELASTIC_API_KEY=<key> \
docker-compose up -d
```

### Option 2: systemd service (bare metal / VM)

For processes running directly on Linux hosts, install the sidecar as a systemd service:

```ini
# /etc/systemd/system/otel-sidecar.service
[Unit]
Description=OpenTelemetry Telemetry Sidecar
After=network.target
Documentation=https://github.com/gmoskovicz/edot-autopilot

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/edot-autopilot/otel-sidecar/otel-sidecar.py
Environment=OTEL_SERVICE_NAME=legacy-service-name
Environment=ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
Environment=ELASTIC_API_KEY=<key>
Environment=OTEL_DEPLOYMENT_ENVIRONMENT=production
Environment=SIDECAR_PORT=9411
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable otel-sidecar
sudo systemctl start otel-sidecar
sudo systemctl status otel-sidecar
```

### Option 3: Windows service (for Windows hosts)

Use NSSM (Non-Sucking Service Manager):

```powershell
# Install Python 3 first
winget install Python.Python.3.12

# Install dependencies
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

# Clone repo
git clone https://github.com/gmoskovicz/edot-autopilot C:\opt\edot-autopilot

# Install as Windows service using NSSM
nssm install OtelSidecar "C:\Python312\python.exe" "C:\opt\edot-autopilot\otel-sidecar\otel-sidecar.py"
nssm set OtelSidecar AppEnvironmentExtra "OTEL_SERVICE_NAME=windows-legacy-service"
nssm set OtelSidecar AppEnvironmentExtra+ "ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io"
nssm set OtelSidecar AppEnvironmentExtra+ "ELASTIC_API_KEY=<key>"
nssm set OtelSidecar AppEnvironmentExtra+ "OTEL_DEPLOYMENT_ENVIRONMENT=production"
nssm set OtelSidecar Start SERVICE_AUTO_START
nssm start OtelSidecar
```

### Option 4: Background process (development / testing)

For quick testing, run the sidecar as a background process:

```bash
export OTEL_SERVICE_NAME=my-service
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<key>

python3 otel-sidecar/otel-sidecar.py &
echo $! > /tmp/otel-sidecar.pid
```

## Security considerations

**Network binding**: The sidecar binds exclusively to `127.0.0.1`. It is not accessible from any external network interface. There is no authentication on the sidecar endpoint — it is only accessible to processes on the same host (or in the same Docker network namespace).

**Credentials**: The `ELASTIC_API_KEY` is stored in the sidecar's environment and never exposed through the HTTP API. The legacy process never handles Elastic credentials directly.

**Permissions**: The sidecar requires no elevated permissions. It runs as a non-root user. It does not read files, touch the filesystem (beyond logging), or open any privileged ports.

**Outbound traffic**: The sidecar makes outbound HTTPS connections to your Elastic Cloud endpoint on port 443. Ensure your firewall allows outbound 443 from the host.

**PII**: The sidecar does not inspect or filter the attributes you send. Do not include PII (names, email addresses, full card numbers) in span attributes. Elastic stores everything you send.

## Performance characteristics

The sidecar is designed to be fire-and-forget from the perspective of the caller:

- **Latency**: A typical `event` POST round-trips in under 5ms on loopback. The legacy process does not need to wait for the Elastic export — the sidecar handles export asynchronously via a `BatchSpanProcessor`.
- **Non-blocking export**: Spans are queued in memory and exported in batches. If the Elastic endpoint is temporarily unreachable, spans queue up and are exported when connectivity resumes (up to the queue size limit).
- **Failure isolation**: If the sidecar is down, the HTTP call from the legacy process fails immediately (after the OS TCP timeout on loopback, which is near-instant). The caller wraps the call in error suppression (`|| true` in Bash, `On Error Resume Next` in VBScript, `try/catch` in PowerShell), so the failure never propagates to the business logic.
- **Resource usage**: The sidecar uses approximately 50MB of RSS memory and negligible CPU at idle. Under load (thousands of events/second), CPU usage scales linearly with span export rate.

## Full docker-compose example with environment file

```yaml
# docker-compose.yml — copy and customize
version: "3.9"

services:
  legacy-app:
    image: ${LEGACY_APP_IMAGE}
    depends_on:
      otel-sidecar:
        condition: service_started
    environment:
      # Your application's own environment variables
      DB_HOST: ${DB_HOST}
      DB_PASSWORD: ${DB_PASSWORD}

  otel-sidecar:
    build:
      context: .
      dockerfile: otel-sidecar/Dockerfile.sidecar
    network_mode: "service:legacy-app"
    environment:
      OTEL_SERVICE_NAME:           ${OTEL_SERVICE_NAME}
      ELASTIC_OTLP_ENDPOINT:       ${ELASTIC_OTLP_ENDPOINT}
      ELASTIC_API_KEY:             ${ELASTIC_API_KEY}
      OTEL_DEPLOYMENT_ENVIRONMENT: ${OTEL_DEPLOYMENT_ENVIRONMENT:-production}
      SIDECAR_PORT:                ${SIDECAR_PORT:-9411}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9411').read()"]
      interval: 10s
      timeout:  3s
      retries:  3
```

```bash
# .env (never commit this file — add to .gitignore)
OTEL_SERVICE_NAME=cobol-payment-processor
ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
ELASTIC_API_KEY=<your-api-key>
OTEL_DEPLOYMENT_ENVIRONMENT=production
LEGACY_APP_IMAGE=your-registry/cobol-app:latest
DB_HOST=your-database-host
DB_PASSWORD=your-db-password
```

## Verifying the sidecar is working

### Test with curl

```bash
curl -s -X POST http://127.0.0.1:9411 \
  -H "Content-Type: application/json" \
  -d '{"action":"event","name":"test.span","attributes":{"test":"true","environment":"local"}}'
# Expected: {"ok": true}
```

### Check Kibana within 60 seconds

1. Navigate to Kibana → Observability → APM → Services
2. Your `OTEL_SERVICE_NAME` should appear as a service
3. Click the service → Transactions tab
4. You should see `test.span` listed

### Sidecar logs

The sidecar logs span export confirmations to stdout. When running as systemd:

```bash
journalctl -u otel-sidecar -f
```

When running in Docker:

```bash
docker-compose logs -f otel-sidecar
```

## Related

- [OpenTelemetry for Legacy Runtimes — overview and tier model](./opentelemetry-legacy-runtimes.md)
- [OpenTelemetry for COBOL](./opentelemetry-cobol.md)
- [OpenTelemetry for Perl](./opentelemetry-perl.md)
- [OpenTelemetry for Bash / Shell Scripts](./opentelemetry-bash-shell-scripts.md)
- [OpenTelemetry for PowerShell](./opentelemetry-powershell.md)
- [OpenTelemetry for Classic ASP / VBScript](./opentelemetry-classic-asp-vbscript.md)
- [Business Span Enrichment](./business-span-enrichment.md)
- [otel-sidecar.py source](../otel-sidecar/otel-sidecar.py)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other developers dealing with legacy runtime observability find this solution.
