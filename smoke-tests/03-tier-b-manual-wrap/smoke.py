#!/usr/bin/env python3
"""
Smoke test: Tier B — Manual OTel wrapping of a legacy "custom framework" handler.

Simulates a Python 2.7-era app with a custom HTTP dispatch layer
(no EDOT auto-instrumentation available). We wrap each handler manually.

Run:
    cd smoke-tests && python3 03-tier-b-manual-wrap/smoke.py
"""

import os, sys, time, uuid, random
from pathlib import Path

# Load .env
env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanKind

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"].rstrip("/")
API_KEY  = os.environ["ELASTIC_API_KEY"]
SVC      = "smoke-tier-b-manual-wrap"

resource = Resource.create({"service.name": SVC, "service.version": "smoke",
                            "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")})
exporter = OTLPSpanExporter(endpoint=f"{ENDPOINT}/v1/traces",
                            headers={"Authorization": f"ApiKey {API_KEY}"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SVC)


# ── Tier B pattern: instrument_handler ────────────────────────────────────────
def instrument_handler(fn, route: str, method: str = "POST"):
    """Wraps any legacy handler with an OTel span. One-line per entry point."""
    def wrapped(*args, **kwargs):
        with tracer.start_as_current_span(
            f"{method} {route}", kind=SpanKind.SERVER,
            attributes={"http.method": method, "http.route": route},
        ) as span:
            try:
                result = fn(*args, **kwargs)
                span.set_attribute("http.status_code", result.get("status_code", 200))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
    return wrapped


# ── Legacy business logic (unchanged) ────────────────────────────────────────
def _legacy_process_order(order_id, amount, tier):
    """Original code — NOT modified. Span context available via get_current_span()."""
    span = trace.get_current_span()
    # Phase 3 enrichment added inside the handler
    span.set_attribute("order.id",        order_id)
    span.set_attribute("order.value_usd", amount)
    span.set_attribute("customer.tier",   tier)
    fraud = random.uniform(0, 1)
    span.set_attribute("fraud.score",    round(fraud, 3))
    span.set_attribute("fraud.decision", "blocked" if fraud > 0.85 else "approved")
    if fraud > 0.85:
        return {"status": "blocked",   "status_code": 402}
    return {"status": "confirmed", "status_code": 201}

def _legacy_get_invoice(invoice_id, customer_id):
    span = trace.get_current_span()
    span.set_attribute("invoice.id",      invoice_id)
    span.set_attribute("customer.id",     customer_id)
    span.set_attribute("invoice.amount",  random.uniform(100, 5000))
    return {"status": "found", "status_code": 200}


# Wrap once at startup — existing call sites are unchanged
process_order = instrument_handler(_legacy_process_order, "/api/orders")
get_invoice   = instrument_handler(_legacy_get_invoice,   "/api/invoices", "GET")


# ── Run smoke ─────────────────────────────────────────────────────────────────
print(f"\n[{SVC}] Sending manually-wrapped spans to {ENDPOINT}...")

process_order(f"ORD-{uuid.uuid4().hex[:6].upper()}", 4200.00, "enterprise")
process_order(f"ORD-{uuid.uuid4().hex[:6].upper()}", 29.99,   "free")
get_invoice(f"INV-{uuid.uuid4().hex[:6].upper()}",   "CUST-PRO-007")

provider.force_flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
