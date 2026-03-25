#!/usr/bin/env python3
"""
Smoke test: Tier B — Manual OTel wrapping, full O11y (traces + logs + metrics).

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

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
SVC      = "smoke-tier-b-manual-wrap"

# ── Bootstrap ─────────────────────────────────────────────────────────────────
o11y   = O11yBootstrap(SVC, ENDPOINT, API_KEY,
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer = o11y.tracer
logger = o11y.logger
meter  = o11y.meter

request_counter = meter.create_counter("handler.requests",
                    description="Total requests to legacy handlers")
handler_latency = meter.create_histogram("handler.duration_ms",
                    description="Legacy handler execution time", unit="ms")
fraud_gauge     = meter.create_histogram("handler.fraud_score",
                    description="Fraud scores seen at billing handler")


# ── Tier B pattern: instrument_handler ────────────────────────────────────────
def instrument_handler(fn, route: str, method: str = "POST"):
    """Wraps any legacy handler with an OTel span. One-line per entry point."""
    def wrapped(*args, **kwargs):
        t0 = time.time()
        with tracer.start_as_current_span(
            f"{method} {route}", kind=SpanKind.SERVER,
            attributes={"http.request.method": method, "http.route": route},
        ) as span:
            try:
                result = fn(*args, **kwargs)
                status = result.get("status_code", 200)
                span.set_attribute("http.response.status_code", status)
                request_counter.add(1, attributes={"http.route": route, "http.response.status_code": str(status)})
                logger.info(
                    f"handler {method} {route} returned {status}",
                    extra={"http.route": route, "http.request.method": method,
                           "http.response.status_code": status},
                )
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_attribute("error.type", type(e).__name__)
                span.set_status(StatusCode.ERROR)
                logger.error(
                    f"handler {method} {route} raised exception: {e}",
                    extra={"http.route": route, "error.type": type(e).__name__},
                )
                raise
            finally:
                handler_latency.record(
                    (time.time() - t0) * 1000,
                    attributes={"http.route": route, "http.request.method": method},
                )
    return wrapped


# ── Legacy business logic (unchanged) ────────────────────────────────────────
def _legacy_process_order(order_id, amount, tier):
    """Original code — NOT modified. Span context available via get_current_span()."""
    span = trace.get_current_span()
    span.set_attribute("order.id",        order_id)
    span.set_attribute("order.value_usd", amount)
    span.set_attribute("customer.tier",   tier)
    fraud = random.uniform(0, 1)
    span.set_attribute("fraud.score",    round(fraud, 3))
    decision = "blocked" if fraud > 0.85 else "approved"
    span.set_attribute("fraud.decision", decision)

    fraud_gauge.record(round(fraud, 3), attributes={"customer.tier": tier})

    if fraud > 0.85:
        logger.warning(
            "order blocked by fraud engine",
            extra={"order.id": order_id, "fraud.score": round(fraud, 3),
                   "customer.tier": tier},
        )
        return {"status": "blocked", "status_code": 402}

    logger.info(
        "order confirmed",
        extra={"order.id": order_id, "order.value_usd": amount, "customer.tier": tier},
    )
    return {"status": "confirmed", "status_code": 201}

def _legacy_get_invoice(invoice_id, customer_id):
    span = trace.get_current_span()
    span.set_attribute("invoice.id",     invoice_id)
    span.set_attribute("customer.id",    customer_id)
    amount = random.uniform(100, 5000)
    span.set_attribute("invoice.amount", round(amount, 2))
    logger.info(
        "invoice retrieved",
        extra={"invoice.id": invoice_id, "customer.id": customer_id,
               "invoice.amount": round(amount, 2)},
    )
    return {"status": "found", "status_code": 200}


# Wrap once at startup — existing call sites are unchanged
process_order = instrument_handler(_legacy_process_order, "/api/orders")
get_invoice   = instrument_handler(_legacy_get_invoice,   "/api/invoices", "GET")


# ── Run smoke ─────────────────────────────────────────────────────────────────
print(f"\n[{SVC}] Sending manually-wrapped spans + logs + metrics to Elastic...")

process_order(f"ORD-{uuid.uuid4().hex[:6].upper()}", 4200.00, "enterprise")
process_order(f"ORD-{uuid.uuid4().hex[:6].upper()}", 29.99,   "free")
process_order(f"ORD-{uuid.uuid4().hex[:6].upper()}", 850.00,  "pro")
get_invoice(f"INV-{uuid.uuid4().hex[:6].upper()}",   "CUST-PRO-007")
get_invoice(f"INV-{uuid.uuid4().hex[:6].upper()}",   "CUST-ENT-001")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
