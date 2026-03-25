# OpenTelemetry Semantic Conventions — Quick Reference

This file is the authoritative cheatsheet for instrumentation in this repo.
AI coding assistants MUST follow these rules when generating any OTel instrumentation code.

---

## HTTP Span Attributes (Stable, semconv 1.20+)

**ALWAYS use the new names. The old names are deprecated.**

| ❌ Deprecated | ✅ Current (stable) |
|---|---|
| `http.method` | `http.request.method` |
| `http.status_code` | `http.response.status_code` |
| `http.url` | `url.full` |
| `http.target` | `url.path` (+ `url.query` if present) |
| `http.scheme` | `url.scheme` |
| `http.flavor` | `network.protocol.version` |
| `http.user_agent` | `user_agent.original` |
| `net.peer.name` | `server.address` |
| `net.peer.port` | `server.port` |
| `net.peer.ip` | `network.peer.address` |
| `http.client_ip` | `client.address` |

Example HTTP server span:
```python
with tracer.start_as_current_span("GET /api/products/{id}", kind=SpanKind.SERVER) as span:
    span.set_attribute("http.request.method", "GET")
    span.set_attribute("url.path", "/api/products/123")
    span.set_attribute("url.scheme", "https")
    span.set_attribute("http.route", "/api/products/{id}")
    span.set_attribute("http.response.status_code", 200)
    span.set_attribute("server.address", "api.example.com")
    span.set_attribute("user_agent.original", "Mozilla/5.0 ...")
```

Example HTTP client span:
```python
with tracer.start_as_current_span("GET", kind=SpanKind.CLIENT) as span:
    span.set_attribute("http.request.method", "GET")
    span.set_attribute("url.full", "https://catalog-service/api/products")
    span.set_attribute("server.address", "catalog-service")
    span.set_attribute("server.port", 443)
    span.set_attribute("http.response.status_code", 200)
    span.set_attribute("service.peer.name", "catalog-service")  # required for APM service maps
```

---

## Database Span Attributes (Stable, semconv 1.22+)

**ALWAYS use the new names.**

| ❌ Deprecated | ✅ Current (stable) |
|---|---|
| `db.system` | `db.system.name` |
| `db.statement` | `db.query.text` |
| `db.operation` | `db.operation.name` |
| `db.sql.table` | `db.collection.name` |
| `db.name` | `db.namespace` |

Example:
```python
with tracer.start_as_current_span("SELECT users", kind=SpanKind.CLIENT) as span:
    span.set_attribute("db.system.name", "postgresql")
    span.set_attribute("db.operation.name", "SELECT")
    span.set_attribute("db.collection.name", "users")
    span.set_attribute("db.query.text", "SELECT * FROM users WHERE id = ?")
    span.set_attribute("db.namespace", "mydb")
    span.set_attribute("server.address", "postgres-host")
    span.set_attribute("service.peer.name", "postgresql")
```

---

## SpanKind — Always Set It

**Every span MUST have an explicit SpanKind. Never rely on the default (INTERNAL).**

```python
from opentelemetry.trace import SpanKind

# HTTP request handler → SERVER
tracer.start_as_current_span("GET /api/users", kind=SpanKind.SERVER)

# Outbound HTTP call, DB call, Redis call, external API → CLIENT
tracer.start_as_current_span("SELECT users", kind=SpanKind.CLIENT)

# Publish to queue/topic → PRODUCER
tracer.start_as_current_span("publish orders.created", kind=SpanKind.PRODUCER)

# Consume from queue/topic → CONSUMER
tracer.start_as_current_span("process orders.created", kind=SpanKind.CONSUMER)

# Internal business logic → INTERNAL (explicit)
tracer.start_as_current_span("validate_payment", kind=SpanKind.INTERNAL)
```

---

## `service.peer.name` — Required on Every CLIENT Span

**Without `service.peer.name`, Elastic APM service maps cannot connect services.**

Set it on every outbound call (HTTP, DB, cache, queue):
```python
span.set_attribute("service.peer.name", "catalog-service")  # the service being called
```

For infrastructure: `"service.peer.name", "postgresql"` / `"redis"` / `"kafka"`

---

## Metric Naming Rules

1. **NO `_total` suffix** — OTel counters never include `_total`. The Prometheus exporter adds it on export automatically.
   - ❌ `http.server.requests_total`
   - ✅ `http.server.request`

2. **Use UCUM units**:
   - Duration: `ms` (milliseconds) or `s` (seconds)
   - Bytes: `By`
   - Ratio/utilization: `1`
   - Currency: `{USD}` (curly-brace annotation, not bare `USD`)
   - Count: `{request}`, `{error}`, `{fault}` (singular)

3. **Instrument type patterns**:
   - Counter: what happened → `http.server.request`, `fraud.block`
   - Histogram: duration/size → `http.server.request.duration`, `db.client.operation.duration`
   - Observable gauge: current state → `system.memory.usage`, `connection.pool.size`

---

## Exception Recording

**`exception.escaped` = True ONLY if the exception propagated past the span boundary (uncaught).**

```python
try:
    risky_operation()
except ValueError as e:
    # Caught and handled — exception did NOT escape
    span.record_exception(e, attributes={"exception.escaped": False})
    span.set_status(StatusCode.ERROR, str(e))
    span.set_attribute("error.type", type(e).__qualname__)
    # continue or return gracefully

# Only use exception.escaped=True when the exception will propagate:
try:
    risky_operation()
except Exception as e:
    span.record_exception(e, attributes={"exception.escaped": True})
    span.set_status(StatusCode.ERROR, str(e))
    span.set_attribute("error.type", type(e).__qualname__)
    raise  # exception escapes the span
```

---

## OS Resource Attributes (Mobile)

`os.type` is **Required** even though the `os.*` group is still in Development status.

| `os.name` | `os.type` value |
|---|---|
| iOS / macOS | `"darwin"` |
| Android / Linux | `"linux"` |
| Windows | `"windows"` |

Always include for mobile:
```python
extra_resource_attrs={
    "os.type":        "darwin",        # Required
    "os.name":        "iOS",           # Recommended
    "os.version":     "17.2.1",        # Recommended
    "os.description": "iOS 17.2.1 (21C66)",  # Recommended
    "os.build_id":    "21C66",         # Recommended
}
```

---

## Core Web Vitals (Browser RUM)

Use **INP** (Interaction to Next Paint), not FID. Chrome deprecated FID in March 2024.

| Metric | Attribute | Unit | Good / NI / Poor |
|---|---|---|---|
| LCP | `webvitals.lcp_ms` | ms | <2500 / <4000 / >4000 |
| INP | `webvitals.inp_ms` | ms | <200 / <500 / >500 |
| CLS | `webvitals.cls_score` | 1 | <0.1 / <0.25 / >0.25 |
| TTFB | `webvitals.ttfb_ms` | ms | <800 / <1800 / >1800 |
| FCP | `webvitals.fcp_ms` | ms | <1800 / <3000 / >3000 |

**Use explicit histogram bucket boundaries aligned with CWV thresholds** so Kibana can show Good/NI/Poor distributions:

```python
from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation

views = [
    View(instrument_name="webvitals.lcp",
         aggregation=ExplicitBucketHistogramAggregation([200,500,1000,2500,4000,10000])),
    View(instrument_name="webvitals.inp",
         aggregation=ExplicitBucketHistogramAggregation([50,100,200,500,1000])),
    View(instrument_name="webvitals.cls",
         aggregation=ExplicitBucketHistogramAggregation([0.01,0.05,0.1,0.15,0.25,0.4])),
    View(instrument_name="webvitals.ttfb",
         aggregation=ExplicitBucketHistogramAggregation([100,200,500,800,1800,3000])),
    View(instrument_name="webvitals.fcp",
         aggregation=ExplicitBucketHistogramAggregation([500,1000,1800,3000,5000])),
]
# Pass views= to MeterProvider
```

---

## Messaging Span Attributes

| ❌ Old | ✅ Current |
|---|---|
| `messaging.operation` = `"send"` | `messaging.operation.type` = `"publish"` |
| `messaging.operation` = `"receive"` | `messaging.operation.type` = `"receive"` |
| `messaging.destination` = `"queue-name"` | `messaging.destination.name` = `"queue-name"` |
| `message.id` | `messaging.message.id` |

Always set: `messaging.system` (e.g. `"kafka"`, `"rabbitmq"`, `"aws_sqs"`, `"sidekiq"`)

---

## Span Events — Add Lifecycle Annotations

Span events appear as timeline markers in Elastic APM trace waterfall. Use them for key state transitions:

```python
# Inside a span:
span.add_event("db.pool.checkout", {"pool.wait_ms": 12, "pool.size": 10})
span.add_event("cache.miss", {"cache.key": "user:123", "cache.backend": "redis"})
span.add_event("ml.model.loaded", {"ml.model_name": "fraud-v3", "ml.load_ms": 340})
span.add_event("payment.auth.initiated", {"payment.provider": "stripe"})
span.add_event("payment.auth.completed", {"payment.auth_code": "AUTH_OK"})
```

Good candidates for span events (not separate spans):
- Cache hit/miss
- Retry attempts
- Auth token refresh
- Model load / warmup complete
- Batch flush
- Connection pool wait

---

## Privacy — `device.id`

`device.id` is Opt-In per OTel semconv and carries a GDPR/privacy warning. Do NOT set raw device identifiers as resource attributes. Use a hashed/anonymized value or omit entirely.

```python
import hashlib
# If you must track device identity, hash it:
hashed = hashlib.sha256(raw_device_id.encode()).hexdigest()[:16]
extra_resource_attrs={"device.id": hashed}
```
