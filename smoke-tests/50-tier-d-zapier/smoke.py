#!/usr/bin/env python3
"""
Smoke test: Tier D — Zapier no-code automation (sidecar simulation).

Simulates Zapier workflow executions submitting observability via the HTTP
sidecar bridge. Business scenario: multi-step lead nurturing automation —
Salesforce new lead → enrich via Clearbit → create HubSpot contact →
send Slack notification → add to Mailchimp sequence.

Run:
    cd smoke-tests && python3 50-tier-d-zapier/smoke.py
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

SVC = "smoke-tier-d-zapier"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

zaps_executed     = meter.create_counter("zapier.zap_executions")
steps_executed    = meter.create_counter("zapier.steps_executed")
zap_duration      = meter.create_histogram("zapier.zap_duration_ms", unit="ms")
step_errors       = meter.create_counter("zapier.step_errors")

LEAD_TRIGGERS = [
    {"zap_id": "ZAP-48291", "lead": {"name": "Alexandra Torres",  "email": "a.torres@techcorp.io",  "company": "TechCorp",   "title": "VP Engineering",  "source": "webinar"}},
    {"zap_id": "ZAP-48291", "lead": {"name": "Benjamin Park",     "email": "b.park@growthco.com",   "company": "GrowthCo",   "title": "Head of Growth",   "source": "demo_request"}},
    {"zap_id": "ZAP-48291", "lead": {"name": "Caroline Mensah",   "email": "c.mensah@enterprise.ai","company": "EntAI",      "title": "CTO",              "source": "referral"}},
]

ZAP_STEPS = [
    {"app": "Salesforce",  "action": "Find Lead",               "latency": (0.20, 0.45)},
    {"app": "Clearbit",    "action": "Enrich Person",            "latency": (0.30, 0.80)},
    {"app": "HubSpot",     "action": "Create/Update Contact",    "latency": (0.15, 0.40)},
    {"app": "Slack",       "action": "Send Channel Message",     "latency": (0.05, 0.15)},
    {"app": "Mailchimp",   "action": "Add/Update Subscriber",    "latency": (0.10, 0.30)},
]

def execute_zap(trigger):
    t0 = time.time()
    run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
    lead   = trigger["lead"]
    errors = 0

    with tracer.start_as_current_span("Zapier.zap_run", kind=SpanKind.INTERNAL,
            attributes={"zapier.zap_id":   trigger["zap_id"],
                        "zapier.run_id":   run_id,
                        "zapier.zap_name": "SF Lead → Enrich → HubSpot → Slack → Mailchimp",
                        "lead.email":      lead["email"],
                        "lead.company":    lead["company"],
                        "lead.source":     lead["source"]}) as span:

        for step in ZAP_STEPS:
            step_key = f"{step['app']}.{step['action'].replace('/', '_').replace(' ', '_')}"
            with tracer.start_as_current_span(f"Zapier.step.{step_key}", kind=SpanKind.CLIENT,
                    attributes={"zapier.app":    step["app"],
                                "zapier.action": step["action"],
                                "zapier.run_id": run_id}) as ss:
                lo, hi = step["latency"]
                time.sleep(random.uniform(lo, hi))

                failed = random.random() < 0.04
                if failed:
                    errors += 1
                    ss.set_status(StatusCode.ERROR, f"{step['app']} API error 429")
                    step_errors.add(1, attributes={"zapier.app": step["app"]})
                    logger.warning("zap step failed",
                                   extra={"zapier.run_id": run_id, "zapier.app": step["app"],
                                          "zapier.action": step["action"], "lead.email": lead["email"],
                                          "error.message": f"{step['app']} API error 429"})
                else:
                    steps_executed.add(1, attributes={"zapier.app": step["app"]})

        dur = (time.time() - t0) * 1000
        span.set_attribute("zapier.steps_total",   len(ZAP_STEPS))
        span.set_attribute("zapier.steps_failed",  errors)
        span.set_attribute("zapier.steps_success", len(ZAP_STEPS) - errors)
        span.set_attribute("zapier.duration_ms",   round(dur, 2))
        span.set_attribute("lead.name",            lead["name"])
        span.set_attribute("lead.title",           lead["title"])

        if errors:
            span.set_status(StatusCode.ERROR, f"{errors} step(s) failed")

        zaps_executed.add(1, attributes={"zapier.zap_id":   trigger["zap_id"],
                                          "lead.source":     lead["source"]})
        zap_duration.record(dur, attributes={"zapier.zap_id": trigger["zap_id"]})

        logger.info("zap execution complete",
                    extra={"zapier.zap_id": trigger["zap_id"], "zapier.run_id": run_id,
                           "lead.email": lead["email"], "lead.company": lead["company"],
                           "zapier.steps_success": len(ZAP_STEPS) - errors,
                           "zapier.steps_failed": errors, "zapier.duration_ms": round(dur, 2)})

    return run_id, errors

print(f"\n[{SVC}] Simulating Zapier lead nurturing automation executions...")
for trigger in LEAD_TRIGGERS:
    run_id, errs = execute_zap(trigger)
    icon = "⚠️ " if errs else "✅"
    print(f"  {icon} {run_id}  {trigger['lead']['name']:<22}  {trigger['lead']['company']:<12}  errors={errs}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
