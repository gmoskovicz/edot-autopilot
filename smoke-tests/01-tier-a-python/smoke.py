#!/usr/bin/env python3
"""
Smoke test: Tier A — Python (native OTel SDK, full O11y: traces + logs + metrics).

Sends checkout spans with business attributes, correlated logs, and counters/
histograms directly to Elastic via OTLP/HTTP.

Run:
    cd smoke-tests && python3 01-tier-a-python/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

# Load .env
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry.trace import SpanKind, StatusCode

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")
SVC      = "smoke-tier-a-python"

# ── Bootstrap all three signals ───────────────────────────────────────────────
o11y = O11yBootstrap(SVC, ENDPOINT, API_KEY, ENV)
tracer = o11y.tracer
logger = o11y.logger
meter  = o11y.meter

# Metrics instruments
checkout_counter    = meter.create_counter("checkout.requests",
                        description="Total checkout attempts")
order_value_hist    = meter.create_histogram("checkout.order_value_usd",
                        description="Order value in USD", unit="USD")
fraud_score_hist    = meter.create_histogram("checkout.fraud_score",
                        description="Fraud score distribution (0-1)")
payment_duration    = meter.create_histogram("payment.duration_ms",
                        description="Payment processing latency", unit="ms")

# ── Test data ─────────────────────────────────────────────────────────────────
orders = [
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "value": 4200.00, "tier": "enterprise",
     "fraud": 0.12, "method": "wire_transfer"},
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "value": 29.99,   "tier": "free",
     "fraud": 0.88, "method": "card"},
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "value": 1250.00, "tier": "pro",
     "fraud": 0.34, "method": "paypal"},
]

print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

for order in orders:
    decision = "blocked" if order["fraud"] > 0.85 else "approved"

    with tracer.start_as_current_span("checkout.complete", kind=SpanKind.SERVER) as span:
        span.set_attribute("order.id",           order["id"])
        span.set_attribute("order.value_usd",    order["value"])
        span.set_attribute("customer.tier",      order["tier"])
        span.set_attribute("fraud.score",        order["fraud"])
        span.set_attribute("fraud.decision",     decision)
        span.set_attribute("payment.method",     order["method"])
        span.set_attribute("inventory.reserved", order["fraud"] < 0.85)
        span.set_attribute("test.run_id",        SVC)

        # Nested payment span
        pay_start = time.time()
        with tracer.start_as_current_span("payment.process", kind=SpanKind.CLIENT) as pay:
            pay.set_attribute("payment.provider",   "stripe")
            pay.set_attribute("payment.amount_usd", order["value"])
            time.sleep(0.05)
            if order["fraud"] > 0.85:
                pay.set_attribute("payment.declined", True)
                pay.record_exception(ValueError("payment skipped — fraud block"), attributes={"exception.escaped": True})
                pay.set_status(StatusCode.ERROR, "payment skipped — fraud block")
        pay_ms = (time.time() - pay_start) * 1000

        if order["fraud"] > 0.85:
            span.record_exception(ValueError("Fraud block"), attributes={"exception.escaped": True})
            span.set_status(StatusCode.ERROR, "Fraud block")

        # Metrics — recorded inside span so trace context is attached automatically
        attrs = {"customer.tier": order["tier"], "fraud.decision": decision}
        checkout_counter.add(1, attributes=attrs)
        order_value_hist.record(order["value"], attributes=attrs)
        fraud_score_hist.record(order["fraud"],  attributes={"customer.tier": order["tier"]})
        payment_duration.record(pay_ms,          attributes={"payment.method": order["method"]})

        # Structured log — trace.id auto-populated from active span context
        if order["fraud"] > 0.85:
            logger.warning(
                "checkout blocked by fraud engine",
                extra={"order.id": order["id"], "fraud.score": order["fraud"],
                       "customer.tier": order["tier"], "order.value_usd": order["value"]},
            )
        else:
            logger.info(
                "checkout completed successfully",
                extra={"order.id": order["id"], "payment.method": order["method"],
                       "customer.tier": order["tier"], "order.value_usd": order["value"]},
            )

    icon = "🚫" if order["fraud"] > 0.85 else "✅"
    print(f"  {icon} {order['id']}  ${order['value']:>8.2f}  [{order['tier']:10}]  "
          f"fraud={order['fraud']:.2f}  → {decision}")

o11y.flush()
print(f"\n[{SVC}] Done. Kibana → APM → {SVC} | Logs: service.name:{SVC} | "
      f"Metrics: checkout.requests")
