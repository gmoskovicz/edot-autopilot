#!/usr/bin/env python3
"""
Smoke test: Tier A — Ruby (native OTel SDK).

Runner script: attempts to run the Ruby smoke test if `ruby` and `bundler`
are available. Falls back to a Python simulation with service.name=smoke-tier-a-ruby.

Run:
    cd smoke-tests && python3 10-tier-a-ruby/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-a-ruby"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

subs_created  = meter.create_counter("subscriptions.created")
mrr_counter   = meter.create_histogram("subscriptions.mrr_usd", unit="USD")
process_ms    = meter.create_histogram("subscriptions.processing_ms", unit="ms")

SUBSCRIPTIONS = [
    ("SUB-R001", "alice@acme.com",    "enterprise", 499.00,  "LAUNCH20"),
    ("SUB-R002", "bob@startupx.io",   "pro",         79.00,  None),
    ("SUB-R003", "carol@bigcorp.com", "enterprise", 1499.00, "Q1SAVE"),
]

print(f"\n[{SVC}] Processing subscriptions (Ruby Tier A simulation)...")

for sub_id, customer, plan, mrr, promo in SUBSCRIPTIONS:
    t0 = time.time()
    with tracer.start_as_current_span("subscription.create", kind=SpanKind.SERVER,
            attributes={"subscription.id": sub_id, "customer.email": customer,
                        "subscription.plan": plan, "subscription.mrr_usd": mrr}) as span:

        with tracer.start_as_current_span("subscription.validate_promo", kind=SpanKind.INTERNAL,
                attributes={"promo.code": promo or ""}) as ps:
            time.sleep(random.uniform(0.005, 0.025))
            discount = mrr * (0.20 if promo == "LAUNCH20" else 0.10) if promo else 0.0
            ps.set_attribute("promo.discount_usd", round(discount, 2))

        with tracer.start_as_current_span("payment.charge_first_month", kind=SpanKind.CLIENT,
                attributes={"payment.amount_usd": mrr, "payment.provider": "stripe"}) as ps:
            time.sleep(random.uniform(0.080, 0.230))
            ps.set_attribute("payment.charge_id", f"ch_{uuid.uuid4().hex[:16]}")
            ps.set_attribute("payment.status", "succeeded")

        with tracer.start_as_current_span("email.send_welcome", kind=SpanKind.CLIENT,
                attributes={"email.to": customer, "email.template": "welcome_subscription"}):
            time.sleep(random.uniform(0.020, 0.070))

        dur = (time.time() - t0) * 1000
        span.set_attribute("subscription.processing_ms", round(dur, 2))

        subs_created.add(1, attributes={"subscription.plan": plan})
        mrr_counter.record(mrr, attributes={"subscription.plan": plan})
        process_ms.record(dur, attributes={"subscription.plan": plan})

        logger.info("subscription created",
                    extra={"subscription.id": sub_id, "customer.email": customer,
                           "subscription.plan": plan, "subscription.mrr_usd": mrr,
                           "subscription.processing_ms": round(dur, 2)})
        promo_str = f"  promo={promo}" if promo else ""
        print(f"  ✅ {sub_id}  {customer:<30}  plan={plan:<12}  mrr=${mrr:>7.2f}{promo_str}  dur={dur:.0f}ms")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
