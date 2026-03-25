# Tier Implementation Guide

Complete code examples for all four tiers. Reference this file during Phase 2.

---

## Tier A — Native EDOT SDK

### Python (use o11y_bootstrap.py from scripts/)

```python
import os, sys
sys.path.insert(0, ".")  # ensure scripts/ is on path
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

o11y = O11yBootstrap(
    service_name="my-service",
    endpoint=os.environ["ELASTIC_OTLP_ENDPOINT"],
    api_key=os.environ["ELASTIC_API_KEY"],
    env=os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "production"),
)

with o11y.tracer.start_as_current_span("checkout.complete", kind=SpanKind.SERVER) as span:
    span.set_attribute("order.id", order.id)
    span.set_attribute("order.value_usd", order.total / 100)
    span.set_attribute("customer.tier", customer.tier)

o11y.logger.info("checkout completed", extra={"order.id": order.id})
counter = o11y.meter.create_counter("checkout.requests")
counter.add(1, {"customer.tier": customer.tier})

o11y.flush()  # call before process exit
```

### Java

```bash
# Download agent
curl -Lo elastic-otel-javaagent.jar \
  https://github.com/elastic/elastic-otel-java/releases/latest/download/elastic-otel-javaagent.jar

# Run with agent
java \
  -javaagent:elastic-otel-javaagent.jar \
  -Dotel.service.name=my-service \
  -Dotel.exporter.otlp.endpoint=$ELASTIC_OTLP_ENDPOINT \
  -Dotel.exporter.otlp.headers="Authorization=ApiKey $ELASTIC_API_KEY" \
  -Dotel.resource.attributes=deployment.environment=production \
  -jar myapp.jar
```

```java
// Manual span (inside code the agent doesn't auto-detect)
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.*;

Tracer tracer = GlobalOpenTelemetry.getTracer("my-module");
Span span = tracer.spanBuilder("processOrder")
    .setSpanKind(SpanKind.INTERNAL)
    .setAttribute("order.id", orderId)
    .setAttribute("order.value_usd", orderValue)
    .startSpan();
try (Scope scope = span.makeCurrent()) {
    // business logic here
} catch (Exception e) {
    span.recordException(e);
    span.setStatus(StatusCode.ERROR, e.getMessage());
    throw e;
} finally {
    span.end();
}
```

### Node.js

```bash
npm install @elastic/opentelemetry-node
```

```javascript
// index.js — must be first import
require('@elastic/opentelemetry-node');

// Or via environment variable (no code change):
// NODE_OPTIONS="--require @elastic/opentelemetry-node" node server.js
```

```bash
# Environment variables
export OTEL_SERVICE_NAME=my-node-service
export OTEL_EXPORTER_OTLP_ENDPOINT=$ELASTIC_OTLP_ENDPOINT
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=ApiKey $ELASTIC_API_KEY"
```

### Go

```go
import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
    "go.opentelemetry.io/otel/sdk/trace"
    "go.opentelemetry.io/otel/sdk/resource"
    semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
)

func initOTel(ctx context.Context) (*trace.TracerProvider, error) {
    exp, err := otlptracehttp.New(ctx,
        otlptracehttp.WithEndpointURL(os.Getenv("ELASTIC_OTLP_ENDPOINT")+"/v1/traces"),
        otlptracehttp.WithHeaders(map[string]string{
            "Authorization": "ApiKey " + os.Getenv("ELASTIC_API_KEY"),
        }),
    )
    if err != nil { return nil, err }

    res, _ := resource.New(ctx,
        resource.WithAttributes(semconv.ServiceName(os.Getenv("OTEL_SERVICE_NAME"))),
    )
    tp := trace.NewTracerProvider(
        trace.WithBatcher(exp),
        trace.WithResource(res),
    )
    otel.SetTracerProvider(tp)
    return tp, nil
}
```

---

## Tier B — Manual Span Wrapping

### Python — wrapping a custom framework entry point

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

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
                span.record_exception(e, attributes={"exception.escaped": True})
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(StatusCode.ERROR, str(e))
                raise
    return wrapped

# Apply at startup — existing route handlers are untouched
app.get_handler = instrument_handler(app.get_handler, "/checkout", "POST")
```

### Python — wrapping a legacy class method

```python
import functools
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

tracer = trace.get_tracer("legacy-billing")

def trace_method(span_name: str, **static_attrs):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name, kind=SpanKind.INTERNAL) as span:
                for k, v in static_attrs.items():
                    span.set_attribute(k, v)
                try:
                    return fn(self, *args, **kwargs)
                except Exception as e:
                    span.record_exception(e, attributes={"exception.escaped": True})
                    span.set_status(StatusCode.ERROR, str(e))
                    raise
        return wrapper
    return decorator

class BillingEngine:
    @trace_method("billing.process_invoice", service="billing-engine")
    def process_invoice(self, invoice_id: str, amount: float):
        # existing logic unchanged
        pass
```

### .NET Framework 4.x

```csharp
// NuGet: OpenTelemetry, OpenTelemetry.Exporter.OpenTelemetryProtocol
using OpenTelemetry;
using OpenTelemetry.Trace;
using OpenTelemetry.Resources;

var tracerProvider = Sdk.CreateTracerProviderBuilder()
    .SetResourceBuilder(ResourceBuilder.CreateDefault()
        .AddService(serviceName: "legacy-dotnet-service"))
    .AddSource("my-legacy-app")
    .AddOtlpExporter(opt => {
        opt.Endpoint = new Uri(Environment.GetEnvironmentVariable("ELASTIC_OTLP_ENDPOINT") + "/v1/traces");
        opt.Headers = "Authorization=ApiKey " + Environment.GetEnvironmentVariable("ELASTIC_API_KEY");
    })
    .Build();

var tracer = TracerProvider.Default.GetTracer("my-legacy-app");

// Wrap existing methods
using var span = tracer.StartActiveSpan("order.process");
span.SetAttribute("order.id", orderId);
span.SetAttribute("order.value_usd", amount);
try {
    ProcessOrderInternal(orderId, amount);
} catch (Exception ex) {
    span.RecordException(ex);
    span.SetStatus(Status.Error.WithDescription(ex.Message));
    throw;
}
```

---

## Tier C — Library Monkey-Patching

### Python — wrapping Stripe

```python
import stripe
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

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
            span.record_exception(e, attributes={"exception.escaped": True})
            span.set_attribute("payment.error_code", e.code)
            span.set_status(StatusCode.ERROR, e.user_message)
            raise

stripe.Charge.create = _instrumented_charge_create  # one line — all call sites covered
```

### Python — wrapping boto3 (S3)

```python
import boto3
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

tracer = trace.get_tracer("boto3-s3")

class InstrumentedS3:
    def __init__(self): self._s3 = boto3.client("s3")

    def put_object(self, Bucket, Key, Body, **kwargs):
        with tracer.start_as_current_span("s3.put_object", kind=SpanKind.CLIENT) as span:
            span.set_attribute("aws.s3.bucket", Bucket)
            span.set_attribute("aws.s3.key", Key)
            span.set_attribute("aws.s3.content_length", len(Body) if Body else 0)
            try:
                result = self._s3.put_object(Bucket=Bucket, Key=Key, Body=Body, **kwargs)
                span.set_attribute("aws.request_id", result["ResponseMetadata"]["RequestId"])
                return result
            except Exception as e:
                span.record_exception(e, attributes={"exception.escaped": True})
                span.set_status(StatusCode.ERROR, str(e))
                raise
```

### Python — wrapping Redis

```python
import redis as _redis
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

tracer = trace.get_tracer("redis-instrumentation")
_orig_execute = _redis.client.Redis.execute_command

def _traced_execute(self, *args, **kwargs):
    cmd = args[0] if args else "UNKNOWN"
    with tracer.start_as_current_span(f"redis.{cmd}", kind=SpanKind.CLIENT) as span:
        span.set_attribute("db.system", "redis")
        span.set_attribute("db.operation", cmd)
        if len(args) > 1: span.set_attribute("db.redis.key", str(args[1])[:100])
        try:
            return _orig_execute(self, *args, **kwargs)
        except Exception as e:
            span.record_exception(e, attributes={"exception.escaped": True})
            span.set_status(StatusCode.ERROR, str(e))
            raise

_redis.client.Redis.execute_command = _traced_execute
```

---

## Tier D — Sidecar

See `sidecar-callers.md` for ready-to-paste caller snippets in all legacy languages.
See `scripts/otel-sidecar.py` for the full sidecar server implementation.
See `assets/docker-compose-sidecar.yml` for the Docker deployment pattern.
