#!/usr/bin/env python3
"""
Smoke test: Tier A — Python (native OTel SDK, no framework needed).

Sends a realistic checkout span with business attributes directly to Elastic
via OTLP/HTTP. Verifies the endpoint accepts it (HTTP 200).

Run:
    cd smoke-tests && python3 01-tier-a-python/smoke.py
"""

import os, sys, time, random, uuid
sys.path.insert(0, os.path.dirname(__file__))

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanKind

# ── Load env ──────────────────────────────────────────────────────────────────
from pathlib import Path
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"].rstrip("/")
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")
SVC      = "smoke-tier-a-python"

# ── Bootstrap ─────────────────────────────────────────────────────────────────
resource = Resource.create({
    "service.name": SVC,
    "service.version": "smoke",
    "deployment.environment": ENV,
})
exporter = OTLPSpanExporter(
    endpoint=f"{ENDPOINT}/v1/traces",
    headers={"Authorization": f"ApiKey {API_KEY}"},
)
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(exporter))  # sync for smoke tests
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SVC)

# ── Test spans ────────────────────────────────────────────────────────────────
print(f"\n[{SVC}] Sending spans to {ENDPOINT}...")

orders = [
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "value": 4200.00, "tier": "enterprise", "fraud": 0.12},
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "value": 29.99,   "tier": "free",       "fraud": 0.88},
    {"id": f"ORD-{uuid.uuid4().hex[:6].upper()}", "value": 1250.00, "tier": "pro",        "fraud": 0.34},
]

for order in orders:
    with tracer.start_as_current_span("checkout.complete", kind=SpanKind.SERVER) as span:
        span.set_attribute("order.id",            order["id"])
        span.set_attribute("order.value_usd",     order["value"])
        span.set_attribute("customer.tier",       order["tier"])
        span.set_attribute("fraud.score",         order["fraud"])
        span.set_attribute("fraud.decision",      "blocked" if order["fraud"] > 0.85 else "approved")
        span.set_attribute("payment.method",      random.choice(["card", "wire_transfer", "paypal"]))
        span.set_attribute("inventory.reserved",  order["fraud"] < 0.85)
        span.set_attribute("test.run_id",         SVC)

        # Simulate nested span for payment processing
        with tracer.start_as_current_span("payment.process", kind=SpanKind.CLIENT) as pay_span:
            pay_span.set_attribute("payment.provider",   "stripe")
            pay_span.set_attribute("payment.amount_usd", order["value"])
            time.sleep(0.05)

        status = "blocked" if order["fraud"] > 0.85 else "confirmed"
        if order["fraud"] > 0.85:
            span.set_status(trace.StatusCode.ERROR, "Fraud block")

    icon = "🚫" if order["fraud"] > 0.85 else "✅"
    print(f"  {icon} {order['id']}  ${order['value']:>8.2f}  [{order['tier']:10}]  fraud={order['fraud']:.2f}  → {status}")

# Force flush before exit
provider.force_flush()
print(f"\n[{SVC}] Done. Verify: Kibana → APM → Services → {SVC}")
print(f"         ES query: FROM traces-apm* | WHERE service.name == \"{SVC}\" | LIMIT 5")
