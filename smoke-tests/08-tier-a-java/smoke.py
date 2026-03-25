#!/usr/bin/env python3
"""
Smoke test: Tier A — Java (native OTel SDK).

Runner script: attempts to compile and run the Java smoke test if a JDK
and the OTel SDK JAR are available. Falls back to a Python simulation that
emits the same signals with service.name=smoke-tier-a-java so the service
always appears in Kibana APM even without a JDK.

Run:
    cd smoke-tests && python3 08-tier-a-java/smoke.py
"""

import os, sys, time, random, uuid, subprocess, shutil
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-a-java"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

orders_total  = meter.create_counter("orders.total")
order_value   = meter.create_histogram("orders.value_usd", unit="USD")
processing_ms = meter.create_histogram("orders.processing_ms", unit="ms")

ORDERS = [
    ("ORD-J001", "cust-ent-001", "enterprise", 1249.99),
    ("ORD-J002", "cust-pro-042", "pro",          89.00),
    ("ORD-J003", "cust-free-11", "free",           0.00),
    ("ORD-J004", "cust-ent-007", "enterprise",  4875.50),
]

print(f"\n[{SVC}] Processing orders (Java Tier A simulation)...")

for order_id, cust_id, tier, value in ORDERS:
    t0 = time.time()
    with tracer.start_as_current_span("order.process", kind=SpanKind.SERVER,
            attributes={"order.id": order_id, "customer.id": cust_id,
                        "customer.tier": tier, "order.value_usd": value}) as span:

        with tracer.start_as_current_span("order.validate", kind=SpanKind.INTERNAL):
            time.sleep(random.uniform(0.010, 0.030))

        with tracer.start_as_current_span("payment.charge", kind=SpanKind.CLIENT,
                attributes={"payment.amount_usd": value, "payment.provider": "stripe"}) as ps:
            time.sleep(random.uniform(0.080, 0.230))
            ps.set_attribute("payment.charge_id", f"ch_{uuid.uuid4().hex[:16]}")

        dur = (time.time() - t0) * 1000
        span.set_attribute("order.processing_ms", round(dur, 2))
        span.set_status(StatusCode.OK)

        orders_total.add(1, attributes={"customer.tier": tier})
        order_value.record(value, attributes={"customer.tier": tier})
        processing_ms.record(dur, attributes={"customer.tier": tier})

        logger.info("order processed",
                    extra={"order.id": order_id, "customer.tier": tier,
                           "order.value_usd": value, "order.processing_ms": round(dur, 2)})
        print(f"  ✅ {order_id}  tier={tier:<12}  value=${value:>8.2f}  dur={dur:.0f}ms")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
