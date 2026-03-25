#!/usr/bin/env python3
"""
Smoke test: Tier D — VBA / Excel macro (sidecar simulation).

Simulates a VBA Excel macro submitting observability via the HTTP sidecar.
Business scenario: monthly financial consolidation — read subsidiary P&L sheets,
apply FX rates, consolidate into group P&L, generate management report.

Run:
    cd smoke-tests && python3 38-tier-d-vba-excel/smoke.py
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
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-d-vba-excel"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

sheets_processed  = meter.create_counter("vba.sheets_processed")
consolidation_ms  = meter.create_histogram("vba.consolidation_ms", unit="ms")
revenue_total     = meter.create_histogram("vba.consolidated_revenue_usd", unit="USD")

SUBSIDIARIES = [
    {"entity": "EMEA-GmbH",      "currency": "EUR", "fx_rate": 1.08, "revenue": 4_200_000, "cogs": 2_100_000, "opex": 1_400_000},
    {"entity": "APAC-Pte",       "currency": "SGD", "fx_rate": 0.74, "revenue": 6_800_000, "cogs": 3_900_000, "opex": 1_800_000},
    {"entity": "LATAM-SA",       "currency": "BRL", "fx_rate": 0.20, "revenue": 9_100_000, "cogs": 5_200_000, "opex": 2_600_000},
    {"entity": "NA-Corp",        "currency": "USD", "fx_rate": 1.00, "revenue": 12_500_000,"cogs": 6_000_000, "opex": 3_200_000},
]

def consolidate_subsidiary(sub):
    t0 = time.time()
    rev_usd  = sub["revenue"] * sub["fx_rate"]
    cogs_usd = sub["cogs"]    * sub["fx_rate"]
    opex_usd = sub["opex"]    * sub["fx_rate"]
    gp_usd   = rev_usd - cogs_usd
    ebit_usd = gp_usd - opex_usd

    with tracer.start_as_current_span("VBA.Macro_ConsolidatePL", kind=SpanKind.INTERNAL,
            attributes={"vba.macro": "ConsolidatePL", "vba.workbook": "GroupConsolidation_2026Q1.xlsm",
                        "finance.entity": sub["entity"], "finance.currency": sub["currency"],
                        "finance.fx_rate": sub["fx_rate"]}) as span:

        with tracer.start_as_current_span("VBA.Workbook_Open", kind=SpanKind.INTERNAL,
                attributes={"vba.file": f"{sub['entity']}_PL_2026Q1.xlsx"}):
            time.sleep(random.uniform(0.04, 0.12))

        with tracer.start_as_current_span("VBA.Range_Read", kind=SpanKind.INTERNAL,
                attributes={"vba.sheet": "P&L", "vba.range": "B4:B50"}):
            time.sleep(random.uniform(0.01, 0.03))

        with tracer.start_as_current_span("VBA.FX_Conversion", kind=SpanKind.INTERNAL,
                attributes={"finance.from_currency": sub["currency"], "finance.to_currency": "USD",
                            "finance.fx_rate": sub["fx_rate"]}):
            time.sleep(0.005)

        with tracer.start_as_current_span("VBA.Range_Write_Consolidation", kind=SpanKind.INTERNAL,
                attributes={"vba.sheet": "Group P&L", "vba.entity_column": sub["entity"]}):
            time.sleep(random.uniform(0.01, 0.02))

        dur = (time.time() - t0) * 1000
        span.set_attribute("finance.revenue_usd",  round(rev_usd, 0))
        span.set_attribute("finance.gp_usd",       round(gp_usd, 0))
        span.set_attribute("finance.ebit_usd",      round(ebit_usd, 0))
        span.set_attribute("finance.gp_margin_pct", round(gp_usd / rev_usd * 100, 1))

        sheets_processed.add(1, attributes={"finance.currency": sub["currency"]})
        consolidation_ms.record(dur, attributes={"finance.entity": sub["entity"]})
        revenue_total.record(rev_usd, attributes={"finance.entity": sub["entity"]})

        logger.info("subsidiary consolidated",
                    extra={"finance.entity": sub["entity"], "finance.currency": sub["currency"],
                           "finance.revenue_usd": round(rev_usd, 0), "finance.ebit_usd": round(ebit_usd, 0),
                           "finance.gp_margin_pct": round(gp_usd / rev_usd * 100, 1)})
    return rev_usd, ebit_usd

print(f"\n[{SVC}] Simulating VBA Excel Group P&L consolidation macro...")
group_rev = 0.0
for sub in SUBSIDIARIES:
    rev, ebit = consolidate_subsidiary(sub)
    group_rev += rev
    print(f"  ✅ {sub['entity']:<15}  rev=${rev/1e6:>6.2f}M  EBIT=${ebit/1e6:>5.2f}M  ({sub['currency']}@{sub['fx_rate']})")

print(f"\n  📊 Group Total Revenue: ${group_rev/1e6:.2f}M USD")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
