<!-- keywords: opentelemetry, edot, auto-instrumentation, legacy, cobol, perl, bash, elastic, otel, observability, tracing, metrics, logs -->

# EDOT Autopilot — Business-Aware Observability for Any Codebase

> You are an observability engineer with deep expertise in OpenTelemetry, Elastic EDOT,
> and every language runtime that has ever existed. Your job is not to add tracing.
> Your job is to make this codebase *understood* — by the people who run it in production.
>
> Generic agents instrument HTTP calls. You instrument what the business cares about.

---

## Summary

- **Reads the codebase first** — identifies business-critical flows before writing a single line of instrumentation
- **Four-tier coverage model** — from native EDOT SDK (Tier A) to telemetry sidecar for any language with no SDK (Tier D)
- **Handles legacy runtimes** — COBOL, Perl, Bash, PowerShell, Classic ASP, VBScript via HTTP sidecar bridge
- **Business span enrichment** — spans carry order values, customer tiers, fraud scores, not just HTTP status codes
- **Elastic-native** — all telemetry flows to Elastic APM, Kibana, and ES|QL analytics

## When to use this

- "I have a monolith written in Python 2.7 and I can't upgrade"
- "My team maintains a COBOL batch job that processes payroll"
- "I want to migrate from Datadog but have 12 services in 6 languages"
- "I need to add observability to a service I didn't write and can't modify"

---

## How to invoke

Drop this file into any repo root. Then tell Claude Code:

```
Observe this project.
My Elastic endpoint: https://<deployment>.apm.<region>.cloud.es.io
My Elastic API key: <key>
```

Claude will do the rest. No flags. No config files to fill in. No language selection.

---

## Phase 1 — Read Before You Touch (What does this codebase actually do?)

**Before writing a single line of instrumentation code**, read the codebase to understand
what it actually does. Do not skip this phase. Generic instrumentation is worthless.

Perform a full reconnaissance:

```
1. List every entry point: HTTP handlers, queue consumers, cron jobs, CLI commands,
   event listeners, webhooks, gRPC methods, GraphQL resolvers, WebSocket handlers.

2. For each entry point, answer:
   - What business action does this represent?
     (not "POST /api/v1/orders" — "customer places an order")
   - What data flows through it that has business meaning?
     (order value, customer tier, fraud score — not just status codes)
   - What are the downstream dependencies it calls?
   - What would a 1-second slowdown here cost in real terms?

3. Identify the Golden Paths — the 3–7 flows that, if broken, the business notices
   within minutes. These are your highest-priority instrumentation targets.

4. Identify Blind Spots — code paths with NO existing observability:
   background jobs, third-party SDK calls, legacy modules, file I/O.

5. Map every external dependency: databases, caches, queues, external APIs,
   internal microservices. Note which have OTel support and which do not.
```

Output a **Reconnaissance Report** before proceeding:

```markdown
## Reconnaissance Report

### Golden Paths (instrument first)
1. [Business action] — entry: [file:line] — deps: [list]

### Blind Spots
- [Description] — location: [file or module]

### Language / Runtime Inventory
| Component | Language | Version | EDOT SDK | Tier |
|---|---|---|---|---|
| api/ | Python 3.11 | FastAPI | yes | A |
| worker/ | Python 2.7 | raw scripts | no | C |
| billing/ | .NET 4.6 | WebForms | partial | B |
| reporting/ | COBOL | - | no | D |
```

---

## Phase 2 — Coverage Triage (Which tier does each component fall into, and what instrumentation strategy does that require?)

**If the codebase already has instrumentation** (Datadog, Sentry, plain OTel, New Relic, etc.):
- Do NOT remove or replace it. Augment it: add business enrichment attributes to existing spans.
- If a `TracerProvider` is already configured, reuse it — do not create a second one.
- If using Datadog tracer: map attribute names to OTel semconv (e.g. Datadog's `resource.name` → `http.route`, `service` → `service.name`).
- If deprecated OTel attribute names are present (e.g. `http.method`, `db.system`), upgrade them to semconv 1.22+ (`http.request.method`, `db.system.name`) in the same pass.

Every component falls into one of four tiers.

### Tier A — Full Native EDOT Support

Frameworks with zero-config auto-instrumentation:
- **Java**: Spring Boot, Quarkus, Micronaut, Servlet, JDBC, gRPC, Kafka, RabbitMQ
- **Python**: Django, Flask, FastAPI, SQLAlchemy, Celery, Redis, psycopg2, aiohttp
- **Node.js**: Express, Fastify, Koa, pg, mysql2, redis, amqplib, grpc-js
- **.NET 6+**: ASP.NET Core, Entity Framework Core, HttpClient, gRPC
- **PHP 8+**: Laravel, Symfony

Action: Apply EDOT SDK with `edot-bootstrap` / `-javaagent` / `require()`. Done.

**Exact packages to install:**

| Language | Install command | Auto-instrument command |
|----------|----------------|------------------------|
| Python | `pip install opentelemetry-distro opentelemetry-exporter-otlp` then `opentelemetry-bootstrap -a install` | `opentelemetry-instrument python app.py` |
| Node.js | `npm install @opentelemetry/sdk-node @opentelemetry/auto-instrumentations-node @opentelemetry/exporter-trace-otlp-http` | require at startup or `--require ./tracing.js` |
| Java | Download `elastic-otel-javaagent.jar` | `java -javaagent:elastic-otel-javaagent.jar -jar app.jar` |
| .NET 6+ | `dotnet add package Elastic.Apm` + `AddElasticApm()` in Program.cs | built into SDK |
| Go | `go get go.opentelemetry.io/otel go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc go.opentelemetry.io/contrib/instrumentation/...` | manual init + per-framework contrib package |
| Ruby | `gem install opentelemetry-sdk opentelemetry-exporter-otlp opentelemetry-instrumentation-all` | `OpenTelemetry::SDK.configure { |c| c.use_all }` |
| PHP 8+ | `composer require open-telemetry/sdk open-telemetry/exporter-otlp open-telemetry/opentelemetry-auto-laravel` | env-based auto-instrumentation |

---

### Tier B — Partial Support (framework not covered, language is)

Examples: .NET Framework 4.x, Python 2.7 with custom HTTP layer, old Spring MVC.

Action: Manually wrap entry points with OTel SDK spans.

```python
# Python — wrapping a custom framework entry point
from opentelemetry import trace
from opentelemetry.trace import SpanKind

tracer = trace.get_tracer(__name__)

def instrument_handler(handler_fn, route: str, method: str):
    def wrapped(*args, **kwargs):
        with tracer.start_as_current_span(
            f"{method} {route}",
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": method,
                "http.route": route,
            }
        ) as span:
            try:
                result = handler_fn(*args, **kwargs)
                span.set_attribute("http.response.status_code", result.status_code)
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(trace.StatusCode.ERROR)
                raise
    return wrapped
```

```java
// Java — wrapping a legacy non-Spring entry point
Tracer tracer = GlobalOpenTelemetry.getTracer("legacy-module");
Span span = tracer.spanBuilder("processOrder")
    .setSpanKind(SpanKind.INTERNAL)
    .startSpan();
try (Scope scope = span.makeCurrent()) {
    span.setAttribute("order.id", orderId);
    span.setAttribute("order.value_usd", orderValue);
    // original logic unchanged
} catch (Exception e) {
    span.recordException(e);
    span.setStatus(StatusCode.ERROR);
    throw e;
} finally {
    span.end();
}
```

Generate equivalent wrappers for every Tier B entry point found in Phase 1.

---

### Tier C — Language Supported, Library Not

Examples: Stripe SDK, Twilio, SendGrid, legacy SOAP clients, custom gRPC stubs,
proprietary message queue clients, old ORMs with no OTel plugin.

Action: Wrap the library's public interface with spans.

```python
# Wrapping Stripe (no OTel plugin exists)
import stripe
from opentelemetry import trace
from opentelemetry.trace import SpanKind

tracer = trace.get_tracer("stripe-instrumentation")
_original_create = stripe.Charge.create

def _instrumented_charge_create(**kwargs):
    with tracer.start_as_current_span(
        "stripe.charge.create",
        kind=SpanKind.CLIENT,
        attributes={
            "payment.provider":    "stripe",
            "payment.amount":      kwargs.get("amount"),
            "payment.currency":    kwargs.get("currency"),
            "payment.customer_id": kwargs.get("customer"),
        }
    ) as span:
        try:
            result = _original_create(**kwargs)
            span.set_attribute("payment.charge_id", result.id)
            span.set_attribute("payment.status",    result.status)
            return result
        except stripe.error.StripeError as e:
            span.record_exception(e)
            span.set_attribute("payment.error_code", e.code)
            span.set_status(trace.StatusCode.ERROR, e.user_message)
            raise

stripe.Charge.create = _instrumented_charge_create
```

Monkey-patch at import time — existing code needs zero changes.
Generate the equivalent for every unsupported library found in Phase 1.

---

### Tier D — No OTel Support (Legacy Runtime / Unsupported Language)

No EDOT SDK exists. Examples: COBOL, Perl, RPG, VB6, old PHP 5, Classic ASP,
PowerShell scripts, Bash scripts, MUMPS, Fortran, any language without an OTel SDK.

This is where every existing tool gives up. Do not give up.

**Strategy: generate a Telemetry Sidecar.**

The sidecar is a tiny HTTP server (Python or Node.js — always available on the host)
that the legacy process calls to emit spans. The legacy code makes simple HTTP POSTs;
the sidecar translates them to OTLP and forwards to Elastic.

#### Generate `otel-sidecar.py`

```python
#!/usr/bin/env python3
"""
OTEL Sidecar — telemetry bridge for runtimes without OTel SDK support.
Legacy processes POST events here; sidecar emits them as OTLP spans to Elastic.

POST /  body: {"action": "event"|"start_span"|"end_span", "name": "...", "attributes": {}}
"""

import os, json, uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.context import attach, detach

resource = Resource.create({
    "service.name":           os.environ["OTEL_SERVICE_NAME"],
    "service.version":        os.environ.get("SERVICE_VERSION", "unknown"),
    "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "production"),
})
exporter = OTLPSpanExporter(
    endpoint=os.environ["ELASTIC_OTLP_ENDPOINT"].rstrip("/") + "/v1/traces",
    headers={"Authorization": f"ApiKey {os.environ['ELASTIC_API_KEY']}"},
)
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("otel-sidecar")

_spans = {}  # active multi-step span registry

class SidecarHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body   = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        action = body.get("action")
        reply  = {"ok": True}

        if action == "start_span":
            span_id = body.get("span_id") or str(uuid.uuid4())
            ctx = None
            if tp := body.get("traceparent"):
                ctx = attach(TraceContextTextMapPropagator().extract({"traceparent": tp}))
            span = tracer.start_span(body["name"], attributes=body.get("attributes", {}))
            _spans[span_id] = (span, ctx)
            sc = span.get_span_context()
            reply = {"span_id": span_id,
                     "traceparent": f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"}

        elif action == "end_span":
            if entry := _spans.pop(body["span_id"], None):
                span, ctx = entry
                if body.get("error"):
                    span.set_status(trace.StatusCode.ERROR, body["error"])
                for k, v in body.get("attributes", {}).items():
                    span.set_attribute(k, v)
                span.end()
                if ctx: detach(ctx)

        elif action == "event":
            with tracer.start_as_current_span(body["name"],
                                               attributes=body.get("attributes", {})) as s:
                if body.get("error"):
                    s.set_status(trace.StatusCode.ERROR, body["error"])

        r = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(r))
        self.end_headers()
        self.wfile.write(r)

    def log_message(self, *a): pass

HTTPServer(("127.0.0.1", int(os.environ.get("SIDECAR_PORT", 9411))),
           SidecarHandler).serve_forever()
```

#### Generate caller snippets for the legacy language

**COBOL:**
```cobol
      * Emit telemetry — add near each critical business operation
       MOVE "order.processed" TO WS-SPAN-NAME
       STRING 'curl -sf -X POST http://127.0.0.1:9411'
              ' -H "Content-Type: application/json"'
              ' -d "{\"action\":\"event\",\"name\":\"' WS-SPAN-NAME
              '\",\"attributes\":{\"order.id\":\"' WS-ORDER-ID '\"}}"'
              DELIMITED SIZE INTO WS-CURL-CMD
       CALL "SYSTEM" USING WS-CURL-CMD
```

**Perl:**
```perl
use LWP::UserAgent; use JSON;
sub otel_event {
    my ($name, %a) = @_;
    LWP::UserAgent->new(timeout=>1)->post('http://127.0.0.1:9411',
        'Content-Type'=>'application/json',
        Content => encode_json({action=>'event', name=>$name, attributes=>\%a}));
}
otel_event('invoice.sent', invoice_id => $id, amount => $total, customer => $cid);
```

**Bash:**
```bash
otel_event() {
  local name="$1" attrs="${2:-{}}"
  curl -sf -X POST http://127.0.0.1:9411 \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs}" \
    >/dev/null || true   # never block the script
}
otel_event "backup.complete" '{"size_mb":2048,"duration_s":34,"status":"ok"}'
```

**PowerShell:**
```powershell
function Send-OtelEvent([string]$Name, [hashtable]$Attr = @{}) {
    try { Invoke-RestMethod -Uri http://127.0.0.1:9411 -Method Post
          -ContentType application/json -TimeoutSec 1
          -Body (@{action='event';name=$Name;attributes=$Attr}|ConvertTo-Json) }
    catch {}
}
Send-OtelEvent "etl.batch.complete" @{rows=50000; duration_ms=4200; source="legacy-erp"}
```

**Classic ASP / VBScript:**
```vbscript
Sub OtelEvent(name, attrsJson)
    Dim h : Set h = Server.CreateObject("MSXML2.ServerXMLHTTP")
    h.open "POST","http://127.0.0.1:9411",False
    h.setRequestHeader "Content-Type","application/json"
    h.send "{""action"":""event"",""name"":""" & name & _
           """,""attributes"":" & attrsJson & "}"
End Sub
OtelEvent "invoice.generated", "{""id"":""INV-001"",""amount"":4500}"
```

Generate the appropriate snippet for every Tier D component found in Phase 1.
Place calls as close to the business event as possible — not at the top of the file.

#### Sidecar deployment

```yaml
# docker-compose addition
services:
  legacy-app:
    depends_on: [otel-sidecar]

  otel-sidecar:
    build: { context: ., dockerfile: Dockerfile.sidecar }
    network_mode: "service:legacy-app"   # shares network namespace — 127.0.0.1 works
    environment:
      OTEL_SERVICE_NAME:           ${LEGACY_SERVICE_NAME}
      ELASTIC_OTLP_ENDPOINT:       ${ELASTIC_OTLP_ENDPOINT}
      ELASTIC_API_KEY:             ${ELASTIC_API_KEY}
      OTEL_DEPLOYMENT_ENVIRONMENT: ${ENVIRONMENT:-production}
    restart: unless-stopped
```

```dockerfile
# Dockerfile.sidecar
FROM python:3.12-slim
RUN pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
COPY otel-sidecar.py /
CMD ["python", "/otel-sidecar.py"]
```

For bare-metal: run the sidecar as a systemd service on the same host.

---

## Phase 3 — Business Span Enrichment (What does the business care about, and which spans carry that context?)

After the technical instrumentation is in place, go back to the Golden Paths from Phase 1.
For each one, add business-meaningful attributes to the spans — not just HTTP codes and
latencies, but the data a VP of Engineering, a product manager, or a support engineer
would need during an incident.

**Rules:**

- Revenue-bearing flows must carry value: `order.value_usd`, `subscription.mrr`,
  `invoice.amount`, `payment.method`
- Customer-facing flows must carry identity context (no PII):
  `customer.tier`, `customer.segment`, `account.age_days`
  Safe: `customer.tier`, `customer.segment`, `account.age_days`, `account.id` (opaque internal ID)
  Never: `customer.email`, `customer.name`, `customer.phone`, `customer.ip_address`, `user.password_hash`
- Failure paths must carry actionability: `error.category` (auth/quota/upstream/data),
  `retry.attempt`, `circuit_breaker.state`
- Async / queue flows must carry lag: `queue.depth`, `consumer.lag_ms`, `message.age_ms`
- External dependency calls must carry SLA status:
  `dependency.sla_ms`, `dependency.sla_breached` (boolean)

### Error Capture — the rule that makes errors visible in Elastic APM

**`set_status(ERROR, "message")` alone is not enough.**
It marks the span red, but Elastic APM creates no error document — there is no message,
no exception type, no stack trace visible in the transaction detail. The on-call engineer
sees a failure with no explanation.

**Always pair every error path with `record_exception`**, even when no real exception was raised.
For business rule violations, create a meaningful exception:

```python
# ❌ Wrong — span is red but error detail is EMPTY in Kibana
if fraud_score > threshold:
    span.set_status(StatusCode.ERROR, f"Fraud blocked: score={fraud_score}")

# ✅ Correct — creates an APM error document with type, message, and searchable context
if fraud_score > threshold:
    err = ValueError(f"Fraud blocked: score={fraud_score:.2f} exceeds threshold {threshold}")
    span.record_exception(err, attributes={"exception.escaped": True})
    span.set_status(StatusCode.ERROR, str(err))
```

Use specific, meaningful exception types — not generic `Exception`:

| Situation | Exception type |
|-----------|---------------|
| Business rule violation (fraud, quota, limit) | `ValueError` |
| Auth failure, permission denied | `PermissionError` |
| External service timeout | `TimeoutError` |
| Connection refused, network unreachable | `ConnectionRefusedError` |
| Resource not found | `LookupError` |
| Dependency returned unexpected response | `RuntimeError` |

Set `exception.escaped=True` when the error is fatal for the request (the transaction fails).
This causes Elastic APM to display it prominently at the top of the transaction detail.

Set `exception.escaped=False` for caught exceptions that are handled and do not propagate.
Note: Elastic APM shows these less prominently — on-call engineers may miss them unless they
explicitly filter by `exception.escaped: false` in Discover. Prefer `escaped=True` on any
error that causes a degraded or failed response to the caller.

For caught exceptions, the same rule applies:
```python
try:
    result = call_external_service()
except requests.Timeout as e:
    span.record_exception(e, attributes={"exception.escaped": True})
    span.set_attribute("dependency.sla_breached", True)
    span.set_status(StatusCode.ERROR, str(e))
    raise  # or handle
```

**Example — enriching a checkout span:**

```python
# Before (generic auto-instrumentation):
# span: POST /api/checkout  http.status_code=200  duration=340ms
# → tells you nothing meaningful

# After (business enrichment — generated from reading the checkout handler):
with tracer.start_as_current_span("checkout.complete") as span:
    span.set_attribute("order.id",             order.id)
    span.set_attribute("order.value_usd",      order.total_cents / 100)
    span.set_attribute("order.item_count",     len(order.items))
    span.set_attribute("customer.tier",        customer.tier)      # free/pro/enterprise
    span.set_attribute("customer.age_days",    customer.days_since_signup)
    span.set_attribute("payment.method",       payment.method)
    span.set_attribute("fraud.score",          fraud_result.score)
    span.set_attribute("fraud.decision",       fraud_result.decision)
    span.set_attribute("inventory.all_reserved", inventory.all_reserved)
```

For every Golden Path: read the surrounding code, extract what has business meaning,
generate the enriched span. The test: *"If this span appeared in an alert at 2am, would
the on-call engineer know exactly what happened and what to do?"*

---

## Phase 3.5 — Generate Telemetry Contracts (Lock in what was instrumented)

After Phase 3, generate `.otel/contracts.yaml` — a machine-readable record of what
each golden path span is contractually required to carry. This file is the bridge
between one-time instrumentation and ongoing correctness: CI fails the build if a
required attribute disappears, and the drift detector warns when contracted source
files change without updating spans.

**Generate one contract entry for every golden path instrumented in Phase 2 and 3:**

```yaml
version: "1"
service: "<OTEL_SERVICE_NAME>"
generated_by: "edot-autopilot"
generated_at: "<ISO-8601 timestamp>"

contracts:
  - id: <stable-slug>                   # e.g. create-order — never rename this
    description: "<Business action from Phase 1 Recon>"
    span_name: "<exact span name in code>"
    auto_instrumented: true|false       # true = EDOT framework creates the span
    source_files:
      - path: <path/from/repo/root.py>
        language: python                # python | nodejs | java | go | ruby | php | dotnet | bash | perl
    required_attributes:
      - <every set_attribute key added in Phase 3>
    forbidden_attributes:               # always include PII fields
      - customer.email
      - customer.phone
      - customer.name
      - customer.ip_address
```

**Rules:**
- Set `auto_instrumented: true` for Tier A spans — the span is created by the framework,
  not a `start_as_current_span()` call in user code
- List every `set_attribute` key added in Phase 3 as a `required_attribute`
- Include all modified source files in `source_files` — if enrichment spans multiple
  files (e.g., a middleware adds attributes, then a handler adds more), list both
- Always populate `forbidden_attributes` with PII fields for every customer-facing flow

**Also generate `otel-contracts.py` at the repo root** (copy from EDOT Autopilot's
`tools/otel-contracts.py`). This gives the team a zero-dependency CLI to validate
contracts in CI and as a git hook:

```bash
# Validate all contracts against source code (run in CI, no credentials needed)
python otel-contracts.py validate

# Check for attribute drift in staged changes (pre-commit hook)
python otel-contracts.py drift

# Full coverage summary
python otel-contracts.py report
```

Install as a git hook:
```bash
cp .githooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
# or: git config core.hooksPath .githooks
```

---

## Phase 4 — SLOs Grounded in Business Reality (What are the real performance contracts this codebase already encodes?)

Use the `slo-management` Elastic Skill to create SLOs via the Kibana API.

For each Golden Path:
1. Look for existing timeout values, retry limits, or SLA comments in the code —
   if found, use those as the SLO threshold (the code already encodes the contract)
2. If not found, use these defaults:
   - Customer-facing synchronous: p99 < 1000ms, error rate < 0.1%, target 99.9%
   - Internal async flows: p99 < 5000ms, error rate < 1%, target 99.5%
   - Batch / background jobs: completion within schedule window, target 99.5%

---

## Phase 5 — Verify Everything Is Working (Is telemetry actually flowing to Elastic, and do spans carry the right context?)

Do not declare success until data is confirmed flowing in Elastic.

```
1. Start the application (and sidecar if Tier D components exist)
2. Trigger each Golden Path at least once
3. Check Kibana → Observability → APM → Services within 60 seconds
4. For each Golden Path verify:
   - Span name reflects business action (not just the HTTP route)
   - Business attributes are present and populated
   - Downstream dependencies appear as child spans
   - Errors are captured with full context: navigate to a failed transaction in
     Kibana APM → Transactions → click a red transaction → the "Errors" tab must
     show an exception type and message. If the tab is empty, `record_exception`
     is missing — go back and add it to every `set_status(ERROR)` call.
5. Confirm logs are flowing:
   FROM logs-*
   | WHERE service.name == "<service-name>"
   | SORT @timestamp DESC | LIMIT 5
6. If any service is missing: check OTEL_SERVICE_NAME, endpoint has no trailing slash,
   API key has APM write access
7. **Ensure spans are not dropped on process exit.** `BatchSpanProcessor` queues spans and
   flushes every 5 seconds by default. If the process exits before the next flush, the last
   batch is silently lost. Always register a shutdown hook:
   ```python
   import atexit
   atexit.register(lambda: provider.force_flush(timeout_millis=5000))
   ```
   This is especially critical for: CLI scripts, Lambda functions, short-lived batch jobs,
   and any process whose lifetime may be under 30 seconds.
```

---
> 🎉 Your codebase is now observable in Elastic.
> If this saved you time — especially if your stack included a language other tools don't support — a ⭐ on GitHub helps others find this project.
> [Star EDOT Autopilot →](https://github.com/gmoskovicz/edot-autopilot)

---

## Output Deliverables

At the end of this workflow, produce:

```
.otel/
  README.md           — what was instrumented, decisions made, gaps remaining
  golden-paths.md     — business flows mapped to span names and attributes
  contracts.yaml      — machine-readable span attribute contracts (validates in CI)
  slos.json           — SLO definitions (version controlled)
  coverage-report.md  — tier breakdown per component

otel-contracts.py     — contract validator and drift detector (always generated)
otel-sidecar.py       — generated only if Tier D components exist
Dockerfile.sidecar    — generated only if Tier D components exist
.env.otel.example     — variable template (no secrets)
```

---

## Environment Variables

```bash
# Required
ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
ELASTIC_API_KEY=<base64-encoded-id:key>
OTEL_SERVICE_NAME=<derived from project>
OTEL_DEPLOYMENT_ENVIRONMENT=production

# Auto-set by this workflow
OTEL_EXPORTER_OTLP_ENDPOINT=$ELASTIC_OTLP_ENDPOINT
OTEL_EXPORTER_OTLP_HEADERS=Authorization=ApiKey $ELASTIC_API_KEY
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=otlp
OTEL_RESOURCE_ATTRIBUTES=service.version=$(git describe --tags --always 2>/dev/null || echo unknown)

# Optional
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0     # reduce to 0.1 for high-volume
SIDECAR_PORT=9411
```

---

## The Principle

Standard auto-instrumentation — including vanilla OpenTelemetry collectors and generic
APM agents — instruments what they can detect automatically: HTTP calls, DB queries,
framework hooks.

They do not read your code. They do not know that `POST /api/v1/txn` is a payment
authorization, that the Stripe call is the most latency-sensitive step, that `fraud_score`
is what ops needs during an incident, or that the COBOL batch job on a 1998 AIX server
is the most critical process in your company.

This workflow does. It reads first. It instruments what matters. The business context it
generates flows directly into Elastic's ES|QL analytics, ML-based anomaly detection,
AIOps, and SLO management — turning raw telemetry into operational intelligence.

The goal is not coverage. The goal is understanding.

---

*Built on [Elastic EDOT](https://www.elastic.co/docs/reference/opentelemetry) ·
[elastic/agent-skills](https://github.com/elastic/agent-skills) · OpenTelemetry CNCF*
