#!/usr/bin/env python3
"""
Smoke test: Tier C — Twilio SDK (monkey-patched).

Patches twilio.rest.Client.messages.create() — existing call sites unchanged.
Business scenario: Appointment reminder campaign — send SMS reminders for
upcoming medical appointments, measure delivery rates.

Run:
    cd smoke-tests && python3 20-tier-c-twilio/smoke.py
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

SVC = "smoke-tier-c-twilio"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

sms_counter  = meter.create_counter("twilio.sms.sent")
sms_latency  = meter.create_histogram("twilio.sms.duration_ms", unit="ms")


# ── Mock Twilio SDK ───────────────────────────────────────────────────────────
class _MockMessages:
    @staticmethod
    def create(**kwargs):
        if random.random() < 0.05:
            raise Exception("Twilio API error: 21614 - number not SMS-capable")
        return type("Message", (), {
            "sid":    f"SM{uuid.uuid4().hex}",
            "status": "queued",
            "to":     kwargs.get("to"),
            "from_":  kwargs.get("from_"),
            "body":   kwargs.get("body", "")[:20],
        })()

class _MockClient:
    messages = _MockMessages()

class twilio:
    class rest:
        Client = _MockClient


# ── Tier C: patch messages.create ────────────────────────────────────────────
_orig_create = twilio.rest.Client.messages.create

def _instrumented_create(**kwargs):
    t0       = time.time()
    to_num   = kwargs.get("to", "")
    from_num = kwargs.get("from_", "")
    body_len = len(kwargs.get("body", ""))

    with tracer.start_as_current_span("twilio.messages.create", kind=SpanKind.CLIENT,
        attributes={"sms.to":          to_num, "sms.from":       from_num,
                    "sms.body_length": body_len, "sms.provider": "twilio"}) as span:
        try:
            msg = _orig_create(**kwargs)
            dur = (time.time() - t0) * 1000
            span.set_attribute("sms.message_sid", msg.sid)
            span.set_attribute("sms.status",      msg.status)
            sms_counter.add(1, attributes={"sms.status": "sent"})
            sms_latency.record(dur, attributes={"sms.status": "sent"})
            logger.info("SMS dispatched", extra={"sms.message_sid": msg.sid,
                        "sms.to": to_num, "sms.status": msg.status})
            return msg
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            sms_counter.add(1, attributes={"sms.status": "failed"})
            logger.error("SMS failed", extra={"sms.to": to_num, "error.message": str(e)})
            raise

twilio.rest.Client.messages.create = _instrumented_create   # ← one-line patch


# ── Existing application code — ZERO CHANGES ─────────────────────────────────
def send_appointment_reminder(patient_phone, patient_name, appt_time, clinic):
    client = twilio.rest.Client()
    msg = client.messages.create(
        to=patient_phone,
        from_="+18005550100",
        body=f"Hi {patient_name}, reminder: appt at {clinic} on {appt_time}. Reply STOP to opt out.",
    )
    return msg


reminders = [
    ("+12125550101", "Alice Chen",    "2026-03-26 10:00", "Downtown Medical"),
    ("+13105550102", "Bob Martinez",  "2026-03-26 14:30", "Westside Clinic"),
    ("+16175550103", "Carol Johnson", "2026-03-27 09:00", "North Health"),
    ("+17185550104", "David Kim",     "2026-03-27 11:15", "Downtown Medical"),
    ("+19175550105", "Eve Patel",     "2026-03-28 16:00", "Eastside Health"),
]

print(f"\n[{SVC}] Sending appointment reminders via patched Twilio SDK...")
for phone, name, appt_time, clinic in reminders:
    try:
        msg = send_appointment_reminder(phone, name, appt_time, clinic)
        print(f"  ✅ {name:<18}  {phone}  sid={msg.sid[:16]}...")
    except Exception as e:
        print(f"  🚫 {name:<18}  {phone}  error={e}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
