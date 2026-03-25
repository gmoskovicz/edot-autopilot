#!/usr/bin/env python3
"""
Smoke test: Tier D — IBM RPG / AS400 (sidecar simulation).

Simulates an IBM RPG IV program on AS/400 (IBM i) submitting observability
via the HTTP sidecar bridge. Business scenario: warehouse inventory management —
cycle count reconciliation, stock adjustments, replenishment triggers.

Run:
    cd smoke-tests && python3 36-tier-d-ibm-rpg/smoke.py
"""

import os, sys, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-d-ibm-rpg"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

items_counted      = meter.create_counter("rpg.items_counted")
adjustments_made   = meter.create_counter("rpg.stock_adjustments")
replenishments     = meter.create_counter("rpg.replenishments_triggered")
cycle_count_ms     = meter.create_histogram("rpg.cycle_count_ms", unit="ms")

INVENTORY_ITEMS = [
    {"item": "WH-PRD-00441", "location": "A01-B03", "system_qty": 150, "reorder_point": 50},
    {"item": "WH-PRD-00892", "location": "B02-A11", "system_qty": 8,   "reorder_point": 20},
    {"item": "WH-PRD-01234", "location": "C04-D07", "system_qty": 312, "reorder_point": 100},
    {"item": "WH-PRD-00076", "location": "A03-B01", "system_qty": 0,   "reorder_point": 30},
    {"item": "WH-PRD-02001", "location": "D01-A05", "system_qty": 75,  "reorder_point": 25},
]

def cycle_count(item):
    t0 = time.time()
    counted_qty = item["system_qty"] + random.randint(-5, 5)  # slight variance

    with tracer.start_as_current_span("RPG.WHINV001.CYCLE_COUNT", kind=SpanKind.INTERNAL,
            attributes={"rpg.program": "WHINV001", "rpg.library": "WHPRDLIB",
                        "wh.item_number": item["item"], "wh.location": item["location"],
                        "wh.system_qty": item["system_qty"]}) as span:

        with tracer.start_as_current_span("RPG.WHINV001.READ_INVMST", kind=SpanKind.INTERNAL,
                attributes={"rpg.file": "INVMSTPF", "rpg.operation": "CHAIN",
                            "wh.item_number": item["item"]}):
            time.sleep(random.uniform(0.004, 0.010))

        variance = counted_qty - item["system_qty"]
        if abs(variance) > 0:
            with tracer.start_as_current_span("RPG.WHINV001.WRITE_INVADJF", kind=SpanKind.INTERNAL,
                    attributes={"rpg.file": "INVADJPF", "rpg.operation": "WRITE",
                                "wh.variance_qty": variance}) as s:
                time.sleep(random.uniform(0.006, 0.014))
                s.set_attribute("wh.adjustment_type", "CYCLE-COUNT")
                adjustments_made.add(1, attributes={"wh.item_number": item["item"]})
                logger.warning("stock variance detected",
                               extra={"wh.item_number": item["item"], "wh.variance_qty": variance,
                                      "wh.system_qty": item["system_qty"], "wh.counted_qty": counted_qty})

        needs_replenish = counted_qty <= item["reorder_point"]
        if needs_replenish:
            with tracer.start_as_current_span("RPG.WHINV001.TRIGGER_REPLENISHMENT", kind=SpanKind.INTERNAL,
                    attributes={"rpg.program": "WHORDR001", "wh.item_number": item["item"],
                                "wh.reorder_point": item["reorder_point"]}):
                time.sleep(0.008)
                replenishments.add(1, attributes={"wh.item_number": item["item"]})
                logger.warning("replenishment triggered",
                               extra={"wh.item_number": item["item"], "wh.counted_qty": counted_qty,
                                      "wh.reorder_point": item["reorder_point"]})

        dur = (time.time() - t0) * 1000
        span.set_attribute("wh.counted_qty",  counted_qty)
        span.set_attribute("wh.variance_qty", variance)
        span.set_attribute("wh.needs_replenishment", needs_replenish)
        items_counted.add(1, attributes={"wh.location": item["location"][:3]})
        cycle_count_ms.record(dur, attributes={"rpg.program": "WHINV001"})

        logger.info("cycle count complete",
                    extra={"wh.item_number": item["item"], "wh.counted_qty": counted_qty,
                           "wh.variance_qty": variance, "wh.needs_replenishment": needs_replenish})

    return counted_qty, variance, needs_replenish

print(f"\n[{SVC}] Simulating IBM RPG WHINV001 cycle count program...")
for item in INVENTORY_ITEMS:
    qty, var, repl = cycle_count(item)
    flag = "⚠️ " if repl else "✅"
    print(f"  {flag} {item['item']}  loc={item['location']}  counted={qty}  variance={var:+d}  replenish={repl}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
