#!/usr/bin/env python3
"""
Smoke test: Tier D — COBOL batch job (sidecar simulation).

Simulates a mainframe COBOL batch job submitting observability via the
HTTP sidecar bridge. Business scenario: end-of-month payroll processing —
read employee master, calculate gross/net pay, write disbursement records.

Run:
    cd smoke-tests && python3 33-tier-d-cobol-batch/smoke.py
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

SVC = "smoke-tier-d-cobol-batch"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

records_processed = meter.create_counter("cobol.records_processed")
batch_duration    = meter.create_histogram("cobol.batch_duration_ms", unit="ms")
pay_disbursed     = meter.create_histogram("cobol.gross_pay_usd", unit="USD")
error_counter     = meter.create_counter("cobol.abend_count")

EMPLOYEES = [
    {"emp_id": "EMP-00101", "name": "ALICE JOHNSON",  "dept": "FINANCE",    "hours": 160, "rate": 52.50,  "tax_pct": 0.28},
    {"emp_id": "EMP-00102", "name": "BOB MARTINEZ",   "dept": "OPERATIONS", "hours": 168, "rate": 38.75,  "tax_pct": 0.22},
    {"emp_id": "EMP-00103", "name": "CAROL ZHANG",    "dept": "IT",         "hours": 160, "rate": 71.00,  "tax_pct": 0.32},
    {"emp_id": "EMP-00104", "name": "DAVID OKAFOR",   "dept": "SALES",      "hours": 172, "rate": 45.00,  "tax_pct": 0.24},
    {"emp_id": "EMP-00105", "name": "EVE KOWALSKI",   "dept": "FINANCE",    "hours": 160, "rate": 60.25,  "tax_pct": 0.28},
]

print(f"\n[{SVC}] Simulating COBOL PAYRLL01 batch job...")

with tracer.start_as_current_span("PAYRLL01.JOB", kind=SpanKind.INTERNAL,
        attributes={"cobol.program": "PAYRLL01", "cobol.job_class": "A",
                    "cobol.region_mb": 512, "batch.type": "payroll",
                    "batch.period": "2026-02"}) as job_span:
    t_job = time.time()
    total_gross = 0.0

    with tracer.start_as_current_span("PAYRLL01.READ-EMPMASTER", kind=SpanKind.INTERNAL,
            attributes={"cobol.dd_name": "EMPMASTR", "cobol.vsam_file": "PAYROLL.EMPMASTR.KSF"}) as span:
        time.sleep(0.04)
        span.set_attribute("cobol.records_read", len(EMPLOYEES))
        logger.info("EMPMASTER read complete",
                    extra={"cobol.program": "PAYRLL01", "cobol.step": "READ-EMPMASTER",
                           "cobol.records_read": len(EMPLOYEES)})

    for emp in EMPLOYEES:
        with tracer.start_as_current_span("PAYRLL01.CALC-PAY", kind=SpanKind.INTERNAL,
                attributes={"cobol.employee_id": emp["emp_id"], "cobol.department": emp["dept"]}) as span:
            time.sleep(random.uniform(0.005, 0.015))
            gross = emp["hours"] * emp["rate"]
            net   = gross * (1 - emp["tax_pct"])
            total_gross += gross

            span.set_attribute("payroll.gross_usd",  round(gross, 2))
            span.set_attribute("payroll.net_usd",    round(net, 2))
            span.set_attribute("payroll.tax_pct",    emp["tax_pct"])

            records_processed.add(1, attributes={"cobol.department": emp["dept"]})
            pay_disbursed.record(gross, attributes={"cobol.department": emp["dept"]})

            logger.info("pay calculated",
                        extra={"cobol.employee_id": emp["emp_id"], "payroll.gross_usd": round(gross, 2),
                               "payroll.net_usd": round(net, 2), "cobol.department": emp["dept"]})
            print(f"  ✅ {emp['emp_id']}  {emp['name']:<20}  gross=${gross:>9,.2f}  net=${net:>9,.2f}")

    with tracer.start_as_current_span("PAYRLL01.WRITE-DISBURSEMENTS", kind=SpanKind.INTERNAL,
            attributes={"cobol.dd_name": "DISBFILE", "cobol.seq_file": "PAYROLL.DISB.OUTFILE"}) as span:
        time.sleep(0.02)
        span.set_attribute("cobol.records_written", len(EMPLOYEES))
        span.set_attribute("payroll.total_gross_usd", round(total_gross, 2))
        logger.info("disbursements written",
                    extra={"cobol.step": "WRITE-DISBURSEMENTS", "cobol.records_written": len(EMPLOYEES),
                           "payroll.total_gross_usd": round(total_gross, 2)})

    dur = (time.time() - t_job) * 1000
    job_span.set_attribute("batch.total_gross_usd", round(total_gross, 2))
    job_span.set_attribute("batch.employee_count",  len(EMPLOYEES))
    batch_duration.record(dur, attributes={"cobol.program": "PAYRLL01"})
    print(f"  📊 Total disbursed: ${total_gross:,.2f} across {len(EMPLOYEES)} employees")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
