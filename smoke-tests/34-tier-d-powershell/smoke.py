#!/usr/bin/env python3
"""
Smoke test: Tier D — PowerShell / Windows automation (sidecar simulation).

Simulates a PowerShell script submitting observability via the HTTP sidecar.
Business scenario: Active Directory user provisioning — new employee onboarding
creates AD account, assigns groups, provisions M365 mailbox.

Run:
    cd smoke-tests && python3 34-tier-d-powershell/smoke.py
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

SVC = "smoke-tier-d-powershell"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

users_provisioned  = meter.create_counter("ps.users_provisioned")
provision_duration = meter.create_histogram("ps.provision_duration_ms", unit="ms")
group_assignments  = meter.create_counter("ps.group_assignments")

NEW_HIRES = [
    {"name": "Sarah Chen",     "dept": "Engineering",  "title": "Senior SWE",       "manager": "j.smith",    "groups": ["eng-all", "vpn-access", "github-org"]},
    {"name": "Michael Torres", "dept": "Sales",        "title": "Account Executive", "manager": "a.jackson",  "groups": ["sales-all", "crm-access", "salesforce"]},
    {"name": "Priya Patel",    "dept": "Finance",      "title": "FP&A Analyst",     "manager": "k.roberts",  "groups": ["finance-all", "netsuite-ro", "vpn-access"]},
]

def provision_user(hire):
    samaccount = f"{hire['name'].split()[0][0].lower()}.{hire['name'].split()[-1].lower()}"
    upn        = f"{samaccount}@company.corp"
    t0 = time.time()

    with tracer.start_as_current_span("ps.Invoke-NewHireProvisioning", kind=SpanKind.INTERNAL,
            attributes={"ps.script": "New-HireProvisioning.ps1", "ad.samaccount": samaccount,
                        "ad.upn": upn, "ad.department": hire["dept"],
                        "ad.title": hire["title"]}) as span:

        with tracer.start_as_current_span("ps.New-ADUser", kind=SpanKind.CLIENT,
                attributes={"ad.operation": "New-ADUser", "ad.ou": f"OU={hire['dept']},OU=Users,DC=company,DC=corp"}) as s:
            time.sleep(random.uniform(0.15, 0.35))
            s.set_attribute("ad.object_guid", str(uuid.uuid4()))
            logger.info("AD user created",
                        extra={"ad.samaccount": samaccount, "ad.upn": upn, "ad.department": hire["dept"]})

        for group in hire["groups"]:
            with tracer.start_as_current_span("ps.Add-ADGroupMember", kind=SpanKind.CLIENT,
                    attributes={"ad.operation": "Add-ADGroupMember", "ad.group": group,
                                "ad.samaccount": samaccount}):
                time.sleep(random.uniform(0.02, 0.05))
                group_assignments.add(1, attributes={"ad.group": group, "ad.department": hire["dept"]})

        with tracer.start_as_current_span("ps.Enable-Mailbox", kind=SpanKind.CLIENT,
                attributes={"exchange.operation": "Enable-Mailbox", "exchange.upn": upn,
                            "exchange.plan": "E3"}) as s:
            time.sleep(random.uniform(0.3, 0.6))
            s.set_attribute("exchange.mailbox_guid", str(uuid.uuid4()))
            logger.info("M365 mailbox provisioned",
                        extra={"exchange.upn": upn, "exchange.plan": "E3", "ad.department": hire["dept"]})

        dur = (time.time() - t0) * 1000
        span.set_attribute("ps.provision_duration_ms", round(dur, 2))
        span.set_attribute("ps.groups_assigned", len(hire["groups"]))
        users_provisioned.add(1, attributes={"ad.department": hire["dept"]})
        provision_duration.record(dur, attributes={"ad.department": hire["dept"]})

    return samaccount, upn

print(f"\n[{SVC}] Simulating PowerShell new-hire provisioning script...")
for hire in NEW_HIRES:
    sam, upn = provision_user(hire)
    print(f"  ✅ {hire['name']:<20}  {upn:<35}  groups={len(hire['groups'])}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
