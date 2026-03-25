# Business Span Enrichment Patterns

Reference this file during Phase 3 to add business context to spans.

---

## The enrichment test

For every span on a Golden Path, ask:
*"If this span appeared in a PagerDuty alert at 2am, would the on-call engineer know
exactly what happened, what customer was affected, and what to do next?"*

If the answer is no, add more attributes.

---

## E-commerce / checkout

```python
with tracer.start_as_current_span("checkout.complete", kind=SpanKind.SERVER) as span:
    # Order identity
    span.set_attribute("order.id",              order.id)
    span.set_attribute("order.value_usd",       order.total_cents / 100)
    span.set_attribute("order.item_count",      len(order.items))
    span.set_attribute("order.currency",        order.currency)

    # Customer context (no PII — use IDs and tiers, not names/emails)
    span.set_attribute("customer.id",           customer.id)
    span.set_attribute("customer.tier",         customer.tier)       # free/pro/enterprise
    span.set_attribute("customer.age_days",     customer.days_since_signup)
    span.set_attribute("customer.region",       customer.region)

    # Payment context
    span.set_attribute("payment.method",        payment.method)      # visa/amex/paypal
    span.set_attribute("payment.gateway",       "stripe")
    span.set_attribute("payment.currency",      order.currency)

    # Fraud context
    span.set_attribute("fraud.score",           fraud_result.score)
    span.set_attribute("fraud.decision",        fraud_result.decision)  # allow/block
    span.set_attribute("fraud.risk_tier",       fraud_result.risk_tier) # LOW/MEDIUM/HIGH

    # Fulfillment
    span.set_attribute("inventory.all_reserved", inventory.all_reserved)
    span.set_attribute("warehouse.id",          inventory.warehouse_id)
    span.set_attribute("shipping.method",       order.shipping_method)

    # SLA
    span.set_attribute("checkout.sla_target_ms", 2000)
```

---

## Authentication

```python
with tracer.start_as_current_span("auth.login", kind=SpanKind.SERVER) as span:
    span.set_attribute("auth.method",           "password+mfa")
    span.set_attribute("auth.mfa_channel",      "totp")             # totp/sms/email
    span.set_attribute("user.id",               user.id)            # never email/name
    span.set_attribute("user.tier",             user.tier)
    span.set_attribute("session.ttl_seconds",   3600)

    # Geo / risk signals
    span.set_attribute("request.ip_country",    geo.country)
    span.set_attribute("request.is_vpn",        geo.is_vpn)
    span.set_attribute("auth.risk_score",       risk.score)

    # Failure enrichment
    if login_failed:
        span.set_attribute("auth.failure_reason", "wrong_password")  # not the password!
        span.set_attribute("auth.attempt_number", attempt_count)
        span.set_attribute("auth.account_locked", attempt_count >= 5)
```

---

## Data pipeline / ETL

```python
with tracer.start_as_current_span("pipeline.batch.process") as span:
    span.set_attribute("batch.id",              batch_id)
    span.set_attribute("batch.source",          source_system)
    span.set_attribute("batch.event_type",      event_type)
    span.set_attribute("batch.records_in",      len(raw_records))
    span.set_attribute("batch.records_out",     len(processed))
    span.set_attribute("batch.records_dropped", len(raw_records) - len(processed))
    span.set_attribute("batch.drop_rate_pct",   drop_rate * 100)

    # Pipeline health
    span.set_attribute("pipeline.stage",        "transform")
    span.set_attribute("pipeline.version",      "v2.4.0")
    span.set_attribute("queue.consumer_lag_ms", lag_ms)
    span.set_attribute("queue.depth",           queue_depth)

    # Storage
    span.set_attribute("storage.destination",   s3_path)
    span.set_attribute("storage.format",        "parquet")
    span.set_attribute("storage.size_bytes",    output_size)
```

---

## ML inference

```python
with tracer.start_as_current_span("inference.predict") as span:
    span.set_attribute("model.name",            model_name)
    span.set_attribute("model.version",         model_version)
    span.set_attribute("model.framework",       "pytorch")

    # A/B and canary context
    span.set_attribute("experiment.id",         experiment_id)
    span.set_attribute("experiment.variant",    variant)           # control/treatment

    # Performance
    span.set_attribute("inference.latency_ms",  latency_ms)
    span.set_attribute("inference.cache_hit",   cache_hit)
    span.set_attribute("inference.features_count", len(features))
    span.set_attribute("inference.batch_size",  batch_size)

    # Prediction quality
    span.set_attribute("prediction.confidence", confidence)
    span.set_attribute("prediction.class",      predicted_class)

    # Degradation signals
    span.set_attribute("model.cold_start",      cold_start)
    span.set_attribute("model.fallback_used",   fallback_used)
    span.set_attribute("gpu.device",            "cuda:0")
```

---

## SaaS / multi-tenant

```python
with tracer.start_as_current_span("tenant.provision") as span:
    span.set_attribute("tenant.id",             tenant_id)
    span.set_attribute("tenant.plan",           plan)              # starter/pro/enterprise
    span.set_attribute("tenant.region",         region)

    # Resource allocation context
    span.set_attribute("provision.cpu_cores",   cpu_cores)
    span.set_attribute("provision.memory_gb",   memory_gb)
    span.set_attribute("provision.storage_gb",  storage_gb)
    span.set_attribute("provision.k8s_namespace", namespace)

    # Business context
    span.set_attribute("billing.plan_mrr_usd",  plan_mrr)
    span.set_attribute("billing.trial",         is_trial)
    span.set_attribute("tenant.industry",       industry)
```

---

## Background jobs / batch

```python
with tracer.start_as_current_span("job.payroll.run") as span:
    span.set_attribute("job.id",                job_id)
    span.set_attribute("job.type",              "payroll")
    span.set_attribute("job.schedule",          "0 2 * * 5")       # cron expression
    span.set_attribute("job.period",            "2024-W03")        # what period it covers

    # Volume
    span.set_attribute("job.records_total",     employee_count)
    span.set_attribute("job.records_processed", processed_count)
    span.set_attribute("job.amount_total_usd",  total_payroll_usd)

    # SLA tracking
    span.set_attribute("job.deadline_epoch",    deadline_unix_ts)
    span.set_attribute("job.sla_breached",      completed_at > deadline)
    span.set_attribute("job.retry_attempt",     retry_count)
```

---

## Span events (timeline annotations)

Use `span.add_event()` to mark key milestones inside a long-running span.
These appear as annotated points on the trace waterfall timeline in Kibana APM.

```python
with tracer.start_as_current_span("order.fulfillment") as span:
    span.add_event("fulfillment.payment_authorized", {
        "payment.auth_code": auth_code,
        "payment.gateway":   "stripe",
    })

    # ... reserve inventory ...
    span.add_event("fulfillment.inventory_reserved", {
        "warehouse.id":      warehouse_id,
        "inventory.items":   len(items),
    })

    # ... assign carrier ...
    span.add_event("fulfillment.carrier_assigned", {
        "shipping.carrier":  "UPS",
        "shipping.eta_days": 2,
    })
```

---

## Span links (async / queue patterns)

Use `span.add_link()` or pass `links=` to `start_as_current_span()` when a span
is causally related to another span from a different trace (producer → consumer).

```python
from opentelemetry.trace import Link
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

propagator = TraceContextTextMapPropagator()

# Producer side — save the traceparent when enqueuing
def enqueue_message(message):
    with tracer.start_as_current_span("queue.produce") as producer_span:
        carrier = {}
        propagator.inject(carrier)
        message["_traceparent"] = carrier.get("traceparent", "")
        queue.send(message)

# Consumer side — link back to producer span
def consume_message(message):
    producer_ctx = propagator.extract({"traceparent": message.get("_traceparent", "")})
    producer_span_ctx = next(iter(producer_ctx.values()), None)

    links = [Link(context=producer_span_ctx)] if producer_span_ctx else []

    with tracer.start_as_current_span(
        "queue.consume",
        kind=SpanKind.CONSUMER,
        links=links,
    ) as consumer_span:
        consumer_span.set_attribute("message.age_ms", message.get("age_ms", 0))
        consumer_span.set_attribute("queue.consumer_group", "order-processors")
```

---

## Observable gauges (live state metrics)

Use `create_observable_gauge` for values that represent current state
(active sessions, queue depth, connection pool) rather than events.

```python
import random
from opentelemetry.metrics import Observation

# Active session count (read from your session store)
def active_sessions_callback(options):
    count = session_store.count_active()  # your actual data source
    yield Observation(count, {"region": "us-east-1"})

# Queue depth
def queue_depth_callback(options):
    depth = queue_client.get_approximate_message_count("orders")
    yield Observation(depth, {"queue": "orders", "priority": "high"})

meter.create_observable_gauge(
    "auth.active_sessions",
    [active_sessions_callback],
    description="Currently active authenticated sessions",
)
meter.create_observable_gauge(
    "queue.depth",
    [queue_depth_callback],
    description="Messages waiting in the orders queue",
)
```

---

## Core Web Vitals (Browser RUM)

Use INP (Interaction to Next Paint) — Chrome deprecated FID in March 2024.

```python
from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation

# Configure histogram buckets aligned with CWV Good/NI/Poor thresholds
cwv_views = [
    View(instrument_name="webvitals.lcp",
         aggregation=ExplicitBucketHistogramAggregation([200, 500, 1000, 2500, 4000, 10000])),
    View(instrument_name="webvitals.inp",
         aggregation=ExplicitBucketHistogramAggregation([50, 100, 200, 500, 1000])),
    View(instrument_name="webvitals.cls",
         aggregation=ExplicitBucketHistogramAggregation([0.01, 0.05, 0.1, 0.15, 0.25, 0.4])),
    View(instrument_name="webvitals.ttfb",
         aggregation=ExplicitBucketHistogramAggregation([100, 200, 500, 800, 1800, 3000])),
    View(instrument_name="webvitals.fcp",
         aggregation=ExplicitBucketHistogramAggregation([500, 1000, 1800, 3000, 5000])),
]

# Span attributes (browser RUM)
span.set_attribute("webvitals.lcp_ms", 1240.5)
span.set_attribute("webvitals.inp_ms", 85.0)    # INP, not FID
span.set_attribute("webvitals.cls_score", 0.05)
span.set_attribute("webvitals.ttfb_ms", 320.0)
span.set_attribute("webvitals.fcp_ms", 980.0)
span.set_attribute("browser.name", "Chrome")
span.set_attribute("browser.version", "120.0")
span.set_attribute("browser.platform", "Win32")
span.set_attribute("browser.mobile", False)
span.set_attribute("user_agent.original", "Mozilla/5.0 ...")
```
