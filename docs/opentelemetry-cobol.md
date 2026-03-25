# OpenTelemetry for COBOL — Complete Guide

> How to get distributed traces out of COBOL mainframe programs and into Elastic — without touching the JVM or installing any new runtime on the mainframe.

## The problem

COBOL processes an estimated $3 trillion in transactions every single day. It runs payroll for half the Fortune 500, clears trades at every major exchange, and calculates insurance premiums for hundreds of millions of people. And yet: every major APM vendor — Datadog, Dynatrace, New Relic — simply does not support it. There is no COBOL agent. There is no COBOL SDK. There is no COBOL plugin.

When a COBOL batch job slows down or fails silently, the on-call team is flying blind. They get a call from a downstream service that stopped receiving data. They grep log files. They page the one person who still reads hex dumps.

The root cause is not that COBOL is obscure. The root cause is that every existing observability tool requires an SDK in the same language as the process being monitored. COBOL has no OpenTelemetry SDK. It almost certainly never will.

This leaves a gap that is not theoretical — it is costing engineering teams hours of incident response time on the most business-critical code they run.

## The solution: Telemetry Sidecar

The EDOT Autopilot telemetry sidecar is a tiny Python HTTP server that runs alongside your COBOL process. Your COBOL code makes simple HTTP POST calls (using `curl` via `CALL "SYSTEM"`) to report business events. The sidecar receives those events and translates them into proper OTLP spans, which it forwards to your Elastic cluster.

Architecture:

```
[COBOL Process]
    |
    | CALL "SYSTEM" curl http://127.0.0.1:9411
    |
    v
[otel-sidecar.py :9411]   (Python, same host or shared Docker network)
    |
    | OTLP/HTTP
    v
[Elastic Cloud APM]
    |
    v
[Kibana APM Services View]
```

The COBOL code never knows about OpenTelemetry. It just fires an HTTP request and forgets. The sidecar handles all the trace context, span lifecycle, and protocol translation.

## Step-by-step setup

### Step 1: Deploy the sidecar

Clone the repo and run the sidecar on the same host as your COBOL process:

```bash
git clone https://github.com/gmoskovicz/edot-autopilot
cd edot-autopilot
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

Set the required environment variables:

```bash
export OTEL_SERVICE_NAME=cobol-payment-processor
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<your-base64-encoded-id:key>
export OTEL_DEPLOYMENT_ENVIRONMENT=production

python otel-sidecar/otel-sidecar.py
```

The sidecar binds to `127.0.0.1:9411` by default. It is not reachable from outside the host.

### Step 2: Verify the sidecar is running

```bash
curl -s -X POST http://127.0.0.1:9411 \
  -H "Content-Type: application/json" \
  -d '{"action":"event","name":"sidecar.test","attributes":{"test":"true"}}'
# Expected: {"ok": true}
```

Check Kibana APM within 60 seconds — you should see a service named `cobol-payment-processor` with a span called `sidecar.test`.

### Step 3: Add telemetry calls to your COBOL program

Identify the critical business operations in your program — order processing, payment authorization, batch completion, GL posting — and add `CALL "SYSTEM"` statements immediately after each one.

### Step 4: Verify in Kibana APM

Navigate to Kibana → Observability → APM → Services. Your COBOL service will appear with span names matching your business operations.

## Code example

### Working storage section

Add working storage variables to hold the telemetry data:

```cobol
       WORKING-STORAGE SECTION.
       01 WS-TELEMETRY.
          05 WS-SPAN-NAME     PIC X(80).
          05 WS-ORDER-ID      PIC X(20).
          05 WS-ORDER-AMT     PIC 9(10)V99.
          05 WS-CURL-CMD      PIC X(512).
          05 WS-AMT-STR       PIC X(20).
```

### Instrumenting a payment authorization

```cobol
      * --- Payment Authorization ---
       3000-AUTHORIZE-PAYMENT.
           PERFORM 3100-CALL-PAYMENT-API
           PERFORM 3200-VALIDATE-RESPONSE

      * Emit telemetry after successful authorization
           MOVE "payment.authorized" TO WS-SPAN-NAME
           MOVE WS-ORDER-ID-VALUE TO WS-ORDER-ID
           MOVE WS-AMOUNT-VALUE TO WS-AMT-STR

           STRING 'curl -sf -X POST http://127.0.0.1:9411'
                  ' -H "Content-Type: application/json"'
                  ' -d "{\"action\":\"event\","'
                  '"\"name\":\"' WS-SPAN-NAME '",'
                  '"\"attributes\":{"'
                  '"\"order.id\":\"' WS-ORDER-ID '\",'
                  '"\"order.value_usd\":' WS-AMT-STR ','
                  '"\"payment.method\":\"' WS-PAY-METHOD '\"}}"'
                  DELIMITED SIZE INTO WS-CURL-CMD

           CALL "SYSTEM" USING WS-CURL-CMD
           .
```

### Instrumenting a batch completion event

```cobol
      * --- Batch Job Completion ---
       9999-END-OF-JOB.
           MOVE "payroll.batch.complete" TO WS-SPAN-NAME

           STRING 'curl -sf -X POST http://127.0.0.1:9411'
                  ' -H "Content-Type: application/json"'
                  ' -d "{\"action\":\"event\","'
                  '"\"name\":\"' WS-SPAN-NAME '",'
                  '"\"attributes\":{"'
                  '"\"records.processed\":' WS-RECORD-COUNT ','
                  '"\"run.duration_s\":' WS-RUN-SECS ','
                  '"\"batch.date\":\"' WS-RUN-DATE '\"}}"'
                  DELIMITED SIZE INTO WS-CURL-CMD

           CALL "SYSTEM" USING WS-CURL-CMD
           .
```

### Instrumenting an error path

```cobol
      * --- Emit telemetry on error ---
       8000-HANDLE-ERROR.
           MOVE "payment.authorization.failed" TO WS-SPAN-NAME

           STRING 'curl -sf -X POST http://127.0.0.1:9411'
                  ' -H "Content-Type: application/json"'
                  ' -d "{\"action\":\"event\","'
                  '"\"name\":\"' WS-SPAN-NAME '",'
                  '"\"error\":\"authorization declined\","'
                  '"\"attributes\":{"'
                  '"\"order.id\":\"' WS-ORDER-ID '\",'
                  '"\"decline.code\":\"' WS-DECLINE-CODE '\"}}"'
                  DELIMITED SIZE INTO WS-CURL-CMD

           CALL "SYSTEM" USING WS-CURL-CMD
           .
```

### Docker deployment (if containerized)

If your COBOL process runs in Docker, add the sidecar as a shared-network service:

```yaml
services:
  cobol-app:
    image: your-cobol-image
    depends_on: [otel-sidecar]

  otel-sidecar:
    build:
      context: .
      dockerfile: otel-sidecar/Dockerfile.sidecar
    network_mode: "service:cobol-app"   # shares network — 127.0.0.1 works
    environment:
      OTEL_SERVICE_NAME: cobol-payment-processor
      ELASTIC_OTLP_ENDPOINT: ${ELASTIC_OTLP_ENDPOINT}
      ELASTIC_API_KEY: ${ELASTIC_API_KEY}
      OTEL_DEPLOYMENT_ENVIRONMENT: production
    restart: unless-stopped
```

### systemd service (bare metal)

For mainframe-adjacent Linux hosts, run the sidecar as a systemd service:

```ini
[Unit]
Description=OTEL Telemetry Sidecar
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/edot-autopilot/otel-sidecar/otel-sidecar.py
Environment=OTEL_SERVICE_NAME=cobol-payment-processor
Environment=ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
Environment=ELASTIC_API_KEY=<key>
Environment=OTEL_DEPLOYMENT_ENVIRONMENT=production
Restart=always

[Install]
WantedBy=multi-user.target
```

## What you'll see in Elastic

Once the sidecar is running and your COBOL program has been instrumented, you will see:

- **APM Services**: A service named after your `OTEL_SERVICE_NAME` appears in Kibana → Observability → APM → Services.
- **Business-named spans**: Spans called `payment.authorized`, `payroll.batch.complete`, `order.processed` — not generic HTTP routes, but the names you chose to reflect the actual business action.
- **Custom attributes**: Every attribute you set (`order.id`, `order.value_usd`, `batch.date`, `records.processed`) is searchable and filterable in Kibana Discover and ES|QL.
- **Error tracking**: Error events appear in the Errors tab with your `decline.code` and other context attached.
- **Duration tracking**: You can use `start_span` / `end_span` actions to measure how long critical sections take. The sidecar records span duration automatically.

Example ES|QL query to analyze payment authorizations from COBOL:

```esql
FROM traces-apm*
| WHERE service.name == "cobol-payment-processor"
  AND span.name == "payment.authorized"
| STATS
    total = COUNT(*),
    avg_value = AVG(TO_DOUBLE(attributes.order\.value_usd)),
    p99_duration = PERCENTILE(transaction.duration.us, 99)
  BY bin(@timestamp, 1h)
| SORT @timestamp DESC
```

## Related

- [Telemetry Sidecar Pattern — full documentation](./telemetry-sidecar-pattern.md)
- [OpenTelemetry for Legacy Runtimes — overview](./opentelemetry-legacy-runtimes.md)
- [Business Span Enrichment — adding meaningful attributes](./business-span-enrichment.md)
- [otel-sidecar.py source](../otel-sidecar/otel-sidecar.py)
- [Elastic EDOT documentation](https://www.elastic.co/docs/reference/opentelemetry)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other COBOL developers find this solution.
