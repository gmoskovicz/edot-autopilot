#!/usr/bin/env python3
"""
Smoke test: Tier C — Monkey-patching a third-party library (mock Stripe).

Patches a mock Stripe-like object at import time. Existing call sites
emit spans automatically with zero changes to business logic.

Run:
    cd smoke-tests && python3 04-tier-c-monkey-patch/smoke.py
"""

import os, sys, uuid, random
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
SVC      = "smoke-tier-c-monkey-patch"

resource = Resource.create({"service.name": SVC, "service.version": "smoke",
                            "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")})
exporter = OTLPSpanExporter(endpoint=f"{ENDPOINT}/v1/traces",
                            headers={"Authorization": f"ApiKey {API_KEY}"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SVC)


# ── Mock "Stripe" (simulates any third-party SDK without OTel support) ────────
class _MockStripeCharge:
    @staticmethod
    def create(**kwargs):
        """Simulates stripe.Charge.create — no OTel support built in."""
        return {
            "id":       f"ch_{uuid.uuid4().hex[:16]}",
            "status":   "succeeded",
            "captured": True,
            "amount":   kwargs.get("amount", 0),
        }

class stripe:
    Charge = _MockStripeCharge


# ── Tier C: patch the library's public API ────────────────────────────────────
_orig_charge_create = stripe.Charge.create

def _instrumented_charge_create(**kwargs):
    with tracer.start_as_current_span(
        "stripe.charge.create", kind=SpanKind.CLIENT,
        attributes={
            "payment.provider":    "stripe",
            "payment.amount":      kwargs.get("amount"),
            "payment.currency":    kwargs.get("currency", "usd"),
            "payment.customer_id": kwargs.get("customer", ""),
        },
    ) as span:
        result = _orig_charge_create(**kwargs)
        span.set_attribute("payment.charge_id", result["id"])
        span.set_attribute("payment.status",    result["status"])
        span.set_attribute("payment.captured",  result["captured"])
        return result

stripe.Charge.create = _instrumented_charge_create   # ← one-line patch


# ── Existing application code — ZERO CHANGES ─────────────────────────────────
def process_payment(order_id, amount_cents, currency, customer_id):
    """This is existing business logic. It has no idea it's being observed."""
    charge = stripe.Charge.create(
        amount=amount_cents,
        currency=currency,
        customer=customer_id,
        description=f"Order {order_id}",
    )
    return charge


# ── Run smoke ─────────────────────────────────────────────────────────────────
print(f"\n[{SVC}] Sending monkey-patched Stripe spans to {ENDPOINT}...")

payments = [
    ("ORD-MP-001", 420000,  "usd", "cus_enterprise_001"),
    ("ORD-MP-002", 2999,    "usd", "cus_free_042"),
    ("ORD-MP-003", 125000,  "eur", "cus_pro_007"),
]

for oid, amount, currency, customer in payments:
    charge = process_payment(oid, amount, currency, customer)
    print(f"  ✅ {oid}  ${amount/100:>8.2f} {currency.upper()}  charge={charge['id']}  status={charge['status']}")

provider.force_flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
