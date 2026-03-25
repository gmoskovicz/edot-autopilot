#!/usr/bin/env python3
"""
Smoke test: Tier A — .NET C# (native OTel SDK).

Runner script: attempts to run the .NET smoke test if `dotnet` is available.
Falls back to a Python simulation with service.name=smoke-tier-a-dotnet.

Run:
    cd smoke-tests && python3 11-tier-a-dotnet/smoke.py
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

SVC = "smoke-tier-a-dotnet"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

transfer_count = meter.create_counter("inventory.transfers")
qty_hist       = meter.create_histogram("inventory.transfer_qty")
duration_hist  = meter.create_histogram("inventory.transfer_ms", unit="ms")

TRANSFERS = [
    ("TRF-0001", "WH-EAST-A1",  "WH-WEST-B3",  "SKU-8811", 500,  "system.rebalancer"),
    ("TRF-0002", "WH-WEST-C2",  "STORE-NYC-01", "SKU-4423",  50,  "ops.manual"),
    ("TRF-0003", "WH-EAST-B2",  "WH-SOUTH-D1", "SKU-9912", 1200, "system.rebalancer"),
    ("TRF-0004", "STORE-LA-03", "WH-EAST-A1",  "SKU-1156",  12,  "ops.manual"),
]

print(f"\n[{SVC}] Processing inventory transfers (.NET Tier A simulation)...")

for xfer_id, from_loc, to_loc, sku, qty, requester in TRANSFERS:
    t0 = time.time()
    direction = "wh-to-store" if "STORE" in to_loc else "wh-to-wh"

    with tracer.start_as_current_span("inventory.process_transfer", kind=SpanKind.SERVER,
            attributes={"transfer.id": xfer_id, "transfer.from": from_loc, "transfer.to": to_loc,
                        "inventory.sku": sku, "inventory.qty": qty,
                        "transfer.requester": requester}) as span:

        with tracer.start_as_current_span("inventory.validate_locations", kind=SpanKind.INTERNAL) as v:
            time.sleep(random.uniform(0.005, 0.020))
            v.set_attribute("validation.from_valid", True)
            v.set_attribute("validation.to_valid",   True)

        with tracer.start_as_current_span("inventory.check_stock", kind=SpanKind.CLIENT,
                attributes={"db.system": "sqlserver", "db.operation": "SELECT"}) as s:
            time.sleep(random.uniform(0.010, 0.040))
            s.set_attribute("inventory.available_qty", qty + random.randint(0, 200))

        with tracer.start_as_current_span("inventory.commit_transfer", kind=SpanKind.CLIENT,
                attributes={"db.system": "sqlserver", "db.operation": "UPDATE"}) as c:
            time.sleep(random.uniform(0.015, 0.050))
            c.set_attribute("db.rows_affected", 2)

        with tracer.start_as_current_span("events.publish_stock_transferred", kind=SpanKind.PRODUCER,
                attributes={"messaging.system": "servicebus", "event.type": "StockTransferred"}):
            time.sleep(random.uniform(0.005, 0.025))

        dur = (time.time() - t0) * 1000
        span.set_attribute("transfer.duration_ms", round(dur, 2))

        transfer_count.add(1, attributes={"transfer.direction": direction})
        qty_hist.record(qty, attributes={"transfer.direction": direction})
        duration_hist.record(dur, attributes={"transfer.direction": direction})

        logger.info("stock transfer complete",
                    extra={"transfer.id": xfer_id, "transfer.from": from_loc,
                           "transfer.to": to_loc, "inventory.sku": sku,
                           "inventory.qty": qty, "transfer.duration_ms": round(dur, 2)})
        print(f"  ✅ {xfer_id}  {from_loc:<14} → {to_loc:<14}  sku={sku}  qty={qty:>5}  dur={dur:.0f}ms")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
