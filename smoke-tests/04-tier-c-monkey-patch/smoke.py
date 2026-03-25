#!/usr/bin/env python3
"""
Smoke test: Tier C — Monkey-patching + full O11y (traces + logs + metrics).

Patches a mock Stripe-like object at import time. Existing call sites
emit spans, logs, and metrics automatically with zero changes to business logic.

Run:
    cd smoke-tests && python3 04-tier-c-monkey-patch/smoke.py
"""

import os, sys, uuid, random, time
from pathlib import Path

# Load .env
env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry.trace import SpanKind, StatusCode

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
SVC      = "smoke-tier-c-monkey-patch"

# ── Bootstrap ─────────────────────────────────────────────────────────────────
o11y   = O11yBootstrap(SVC, ENDPOINT, API_KEY,
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer = o11y.tracer
logger = o11y.logger
meter  = o11y.meter

payment_counter  = meter.create_counter("stripe.charge.total",
                     description="Total Stripe charge attempts")
payment_value    = meter.create_histogram("stripe.charge.amount_usd",
                     description="Stripe charge amounts in USD", unit="USD")
payment_latency  = meter.create_histogram("stripe.charge.duration_ms",
                     description="Stripe API call latency", unit="ms")


# ── Mock "Stripe" (simulates any third-party SDK without OTel support) ────────
class _MockStripeCharge:
    @staticmethod
    def create(**kwargs):
        """Simulates stripe.Charge.create — no OTel support built in."""
        # Simulate 10% decline rate
        if random.random() < 0.1:
            raise Exception("card_declined: insufficient funds")
        return {
            "id":       f"ch_{uuid.uuid4().hex[:16]}",
            "status":   "succeeded",
            "captured": True,
            "amount":   kwargs.get("amount", 0),
            "currency": kwargs.get("currency", "usd"),
        }

class stripe:
    Charge = _MockStripeCharge


# ── Tier C: patch the library's public API ────────────────────────────────────
_orig_charge_create = stripe.Charge.create

def _instrumented_charge_create(**kwargs):
    t0 = time.time()
    amount_usd = kwargs.get("amount", 0) / 100
    currency   = kwargs.get("currency", "usd")
    customer   = kwargs.get("customer", "")

    with tracer.start_as_current_span(
        "stripe.charge.create", kind=SpanKind.CLIENT,
        attributes={
            "payment.provider":    "stripe",
            "payment.amount_usd":  amount_usd,
            "payment.currency":    currency,
            "payment.customer_id": customer,
        },
    ) as span:
        try:
            result = _orig_charge_create(**kwargs)
            span.set_attribute("payment.charge_id", result["id"])
            span.set_attribute("payment.status",    result["status"])
            span.set_attribute("payment.captured",  result["captured"])

            duration_ms = (time.time() - t0) * 1000
            payment_counter.add(1, attributes={"payment.status": "succeeded",
                                                "payment.currency": currency})
            payment_value.record(amount_usd,   attributes={"payment.currency": currency})
            payment_latency.record(duration_ms, attributes={"payment.status": "succeeded"})

            logger.info(
                f"stripe charge succeeded",
                extra={"payment.charge_id": result["id"], "payment.amount_usd": amount_usd,
                       "payment.currency": currency, "payment.customer_id": customer},
            )
            return result
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)

            duration_ms = (time.time() - t0) * 1000
            payment_counter.add(1, attributes={"payment.status": "failed",
                                                "payment.currency": currency})
            payment_latency.record(duration_ms, attributes={"payment.status": "failed"})

            logger.error(
                f"stripe charge failed: {e}",
                extra={"payment.amount_usd": amount_usd, "payment.currency": currency,
                       "payment.customer_id": customer, "error.message": str(e)},
            )
            raise

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
print(f"\n[{SVC}] Sending monkey-patched Stripe spans + logs + metrics...")

payments = [
    ("ORD-MP-001", 420000,  "usd", "cus_enterprise_001"),
    ("ORD-MP-002", 2999,    "usd", "cus_free_042"),
    ("ORD-MP-003", 125000,  "eur", "cus_pro_007"),
    ("ORD-MP-004", 89900,   "usd", "cus_pro_015"),
    ("ORD-MP-005", 349900,  "usd", "cus_enterprise_002"),
]

for oid, amount, currency, customer in payments:
    try:
        charge = process_payment(oid, amount, currency, customer)
        print(f"  ✅ {oid}  ${amount/100:>8.2f} {currency.upper()}  "
              f"charge={charge['id']}  status={charge['status']}")
    except Exception as e:
        print(f"  🚫 {oid}  ${amount/100:>8.2f} {currency.upper()}  error={e}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
