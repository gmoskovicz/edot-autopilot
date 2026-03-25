#!/usr/bin/env python3
"""
Smoke test: Tier B — aiohttp web server (no EDOT auto-instrumentation).

Wraps aiohttp Application handlers manually using a middleware-style wrapper.
Business scenario: Healthcare appointment sync — pull appointments from legacy
scheduling system and push to cloud calendar.

Run:
    cd smoke-tests && python3 18-tier-b-aiohttp/smoke.py
"""

import os, sys, uuid, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-b-aiohttp"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

sync_counter    = meter.create_counter("healthcare.appointments.synced")
conflict_counter= meter.create_counter("healthcare.sync.conflicts")
sync_latency    = meter.create_histogram("healthcare.sync.duration_ms", unit="ms")


# ── Tier B: aiohttp handler wrapper ──────────────────────────────────────────
def aiohttp_handler(method, path):
    def decorator(fn):
        def wrapped(request_ctx):
            t0 = time.time()
            with tracer.start_as_current_span(
                f"{method} {path}", kind=SpanKind.SERVER,
                attributes={"http.method": method, "http.route": path, "framework": "aiohttp"},
            ) as span:
                result = fn(request_ctx)
                span.set_attribute("http.status_code", result.get("status", 200))
                sync_latency.record((time.time() - t0) * 1000, attributes={"route": path})
                return result
        return wrapped
    return decorator


# ── Application handlers — UNCHANGED ─────────────────────────────────────────
@aiohttp_handler("POST", "/api/sync/appointments")
def sync_appointments(req):
    patient_id  = req["patient_id"]
    source      = req["source_system"]
    appts       = req["appointments"]
    synced      = 0
    conflicts   = 0

    for appt in appts:
        with tracer.start_as_current_span("appointment.upsert", kind=SpanKind.CLIENT,
            attributes={"patient.id": patient_id, "appointment.id": appt["id"],
                        "appointment.type": appt["type"],
                        "sync.source_system": source}) as span:
            time.sleep(0.01)
            has_conflict = random.random() < 0.2
            span.set_attribute("sync.conflict", has_conflict)

            if has_conflict:
                conflicts += 1
                conflict_counter.add(1, attributes={"appointment.type": appt["type"]})
                logger.warning("appointment sync conflict resolved",
                               extra={"patient.id": patient_id, "appointment.id": appt["id"],
                                      "sync.source_system": source, "appointment.type": appt["type"]})
            else:
                synced += 1
                sync_counter.add(1, attributes={"appointment.type": appt["type"],
                                                 "sync.source_system": source})
                logger.info("appointment synced",
                            extra={"patient.id": patient_id, "appointment.id": appt["id"],
                                   "appointment.type": appt["type"]})

    return {"status": 200, "synced": synced, "conflicts": conflicts}


patients = [
    {"patient_id": "PAT-00123", "source_system": "legacy-cerner",
     "appointments": [
         {"id": "APT-001", "type": "consultation"},
         {"id": "APT-002", "type": "lab-work"},
         {"id": "APT-003", "type": "follow-up"},
     ]},
    {"patient_id": "PAT-00456", "source_system": "legacy-epic",
     "appointments": [
         {"id": "APT-004", "type": "surgery-prep"},
         {"id": "APT-005", "type": "post-op"},
     ]},
]

print(f"\n[{SVC}] Simulating aiohttp healthcare sync handler (manual wrapping)...")
for patient in patients:
    result = sync_appointments(patient)
    print(f"  ✅ {patient['patient_id']}  source={patient['source_system']:<18}  "
          f"synced={result['synced']}  conflicts={result['conflicts']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
