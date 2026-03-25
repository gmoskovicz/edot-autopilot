#!/usr/bin/env python3
"""
Smoke test: Tier D — SAP ABAP (sidecar simulation).

Simulates an SAP ABAP report/function module submitting observability via the
HTTP sidecar. Business scenario: SAP MM purchase order processing —
create PO, check material availability, trigger goods receipt.

Run:
    cd smoke-tests && python3 35-tier-d-sap-abap/smoke.py
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

SVC = "smoke-tier-d-sap-abap"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

po_created     = meter.create_counter("sap.po_created")
po_value       = meter.create_histogram("sap.po_value_eur", unit="EUR")
bapi_duration  = meter.create_histogram("sap.bapi_duration_ms", unit="ms")

PURCHASE_ORDERS = [
    {"vendor": "V-10023", "material": "MAT-5001", "qty": 500,  "unit_price": 12.50,  "plant": "1000", "storage_loc": "0001"},
    {"vendor": "V-10087", "material": "MAT-3214", "qty": 200,  "unit_price": 89.99,  "plant": "1000", "storage_loc": "0002"},
    {"vendor": "V-10055", "material": "MAT-9981", "qty": 1000, "unit_price": 3.75,   "plant": "2000", "storage_loc": "0001"},
]

def process_purchase_order(po):
    po_number = f"4500{random.randint(100000, 999999)}"
    total_val = po["qty"] * po["unit_price"]
    t0 = time.time()

    with tracer.start_as_current_span("ABAP.ZMM_CREATE_PO", kind=SpanKind.INTERNAL,
            attributes={"sap.program": "ZMM_CREATE_PO", "sap.transaction": "ME21N",
                        "sap.vendor": po["vendor"], "sap.material": po["material"],
                        "sap.plant": po["plant"], "sap.quantity": po["qty"]}) as span:

        with tracer.start_as_current_span("ABAP.BAPI_PO_CREATE1", kind=SpanKind.CLIENT,
                attributes={"sap.bapi": "BAPI_PO_CREATE1", "sap.vendor": po["vendor"],
                            "sap.doc_type": "NB"}) as s:
            time.sleep(random.uniform(0.08, 0.25))
            s.set_attribute("sap.po_number", po_number)
            s.set_attribute("sap.po_value_eur", round(total_val, 2))
            logger.info("BAPI_PO_CREATE1 executed",
                        extra={"sap.bapi": "BAPI_PO_CREATE1", "sap.po_number": po_number,
                               "sap.vendor": po["vendor"], "sap.po_value_eur": round(total_val, 2)})

        with tracer.start_as_current_span("ABAP.BAPI_MATERIAL_AVAILABILITY", kind=SpanKind.CLIENT,
                attributes={"sap.bapi": "BAPI_MATERIAL_AVAILABILITY", "sap.material": po["material"],
                            "sap.plant": po["plant"]}) as s:
            time.sleep(random.uniform(0.04, 0.12))
            available = random.choice([True, True, True, False])
            s.set_attribute("sap.material_available", available)
            if not available:
                s.set_attribute("sap.backorder_qty", po["qty"] // 2)
            logger.info("material availability checked",
                        extra={"sap.material": po["material"], "sap.plant": po["plant"],
                               "sap.material_available": available})

        dur = (time.time() - t0) * 1000
        span.set_attribute("sap.po_number",   po_number)
        span.set_attribute("sap.po_value_eur", round(total_val, 2))
        span.set_attribute("sap.bapi_ms",     round(dur, 2))

        po_created.add(1, attributes={"sap.plant": po["plant"], "sap.vendor": po["vendor"]})
        po_value.record(total_val, attributes={"sap.plant": po["plant"]})
        bapi_duration.record(dur, attributes={"sap.bapi": "BAPI_PO_CREATE1"})

    return po_number, total_val

print(f"\n[{SVC}] Simulating SAP ABAP ZMM_CREATE_PO report...")
for po in PURCHASE_ORDERS:
    po_num, val = process_purchase_order(po)
    print(f"  ✅ PO={po_num}  vendor={po['vendor']}  material={po['material']}  val=€{val:,.2f}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
