#!/usr/bin/env python3
"""
Smoke test: Tier D — Classic ASP / VBScript (sidecar simulation).

Simulates a Classic ASP (Active Server Pages) web form submitting observability
via the HTTP sidecar. Business scenario: legacy insurance quote form —
collects applicant data, runs underwriting rules, stores quote in SQL Server.

Run:
    cd smoke-tests && python3 37-tier-d-classic-asp/smoke.py
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

SVC = "smoke-tier-d-classic-asp"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

quotes_generated  = meter.create_counter("asp.quotes_generated")
quote_value       = meter.create_histogram("asp.annual_premium_usd", unit="USD")
page_response_ms  = meter.create_histogram("asp.page_response_ms", unit="ms")
db_query_ms       = meter.create_histogram("asp.db_query_ms", unit="ms")

QUOTE_REQUESTS = [
    {"session_id": "SESS-A1B2", "applicant": "James Wilson",  "age": 34, "zip": "90210", "coverage": "auto",      "vehicle_year": 2019, "annual_miles": 12000},
    {"session_id": "SESS-C3D4", "applicant": "Maria Gomez",   "age": 52, "zip": "10001", "coverage": "homeowner", "home_value": 450000, "year_built": 1992},
    {"session_id": "SESS-E5F6", "applicant": "Robert Kim",    "age": 28, "zip": "60601", "coverage": "auto",      "vehicle_year": 2022, "annual_miles": 8500},
    {"session_id": "SESS-G7H8", "applicant": "Susan Patel",   "age": 61, "zip": "77001", "coverage": "homeowner", "home_value": 320000, "year_built": 2005},
]

def generate_quote(req):
    t0 = time.time()
    quote_id = f"QT-{uuid.uuid4().hex[:8].upper()}"

    with tracer.start_as_current_span("ASP.quote_form.asp", kind=SpanKind.SERVER,
            attributes={"http.method": "POST", "http.url": "/insurance/quote_form.asp",
                        "asp.page": "quote_form.asp", "asp.session_id": req["session_id"],
                        "insurance.coverage_type": req["coverage"]}) as span:

        with tracer.start_as_current_span("ASP.ADODB.Connection.Execute", kind=SpanKind.CLIENT,
                attributes={"db.system": "mssql", "db.operation": "SELECT",
                            "db.name": "InsuranceDB", "db.table": "RatingFactors"}) as s:
            time.sleep(random.uniform(0.05, 0.15))
            s.set_attribute("db.rows_returned", random.randint(3, 8))
            db_query_ms.record((time.time() - t0) * 1000, attributes={"db.operation": "SELECT"})

        with tracer.start_as_current_span("ASP.underwriting_rules", kind=SpanKind.INTERNAL,
                attributes={"insurance.coverage": req["coverage"], "applicant.age": req["age"]}):
            time.sleep(random.uniform(0.02, 0.06))
            base_premium = 1200 if req["coverage"] == "auto" else 1800
            age_factor   = 1.0 + max(0, (25 - req["age"])) * 0.02 if req["age"] < 25 else 1.0
            annual_premium = base_premium * age_factor * random.uniform(0.9, 1.3)

        t_insert = time.time()
        with tracer.start_as_current_span("ASP.ADODB.Connection.Execute", kind=SpanKind.CLIENT,
                attributes={"db.system": "mssql", "db.operation": "INSERT",
                            "db.name": "InsuranceDB", "db.table": "Quotes"}) as s:
            time.sleep(random.uniform(0.03, 0.08))
            s.set_attribute("db.quote_id", quote_id)
            db_query_ms.record((time.time() - t_insert) * 1000, attributes={"db.operation": "INSERT"})

        dur = (time.time() - t0) * 1000
        span.set_attribute("insurance.quote_id",       quote_id)
        span.set_attribute("insurance.annual_premium",  round(annual_premium, 2))
        span.set_attribute("http.status_code",          200)

        quotes_generated.add(1, attributes={"insurance.coverage": req["coverage"]})
        quote_value.record(annual_premium, attributes={"insurance.coverage": req["coverage"]})
        page_response_ms.record(dur, attributes={"asp.page": "quote_form.asp"})

        logger.info("insurance quote generated",
                    extra={"insurance.quote_id": quote_id, "asp.session_id": req["session_id"],
                           "insurance.coverage_type": req["coverage"],
                           "insurance.annual_premium_usd": round(annual_premium, 2),
                           "applicant.age": req["age"]})

    return quote_id, annual_premium

print(f"\n[{SVC}] Simulating Classic ASP insurance quote form submissions...")
for req in QUOTE_REQUESTS:
    qid, premium = generate_quote(req)
    print(f"  ✅ {qid}  {req['applicant']:<18}  {req['coverage']:<12}  premium=${premium:,.2f}/yr")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
