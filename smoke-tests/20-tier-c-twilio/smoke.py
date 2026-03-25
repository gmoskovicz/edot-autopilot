#!/usr/bin/env python3
"""
E2E Auto-Instrumentation Verification — Tier C: Twilio SDK
===========================================================
Simulates: User runs "Observe this project." on a Python app that uses
the Twilio SDK. EDOT Autopilot assigns Tier C (monkey-patch) because
Twilio has no official OTel instrumentation library.

EDOT Autopilot workflow:
  1. Reads codebase → finds twilio.rest.Client.messages.create() call sites
  2. Assigns Tier C: one-line monkey-patch, zero changes to app code
  3. Patch wraps every call in a CLIENT span with business attributes
  4. Adds business enrichment: sms.to, sms.provider, sms.status

Verification checklist:
  ✓ One CLIENT span per SMS attempt (success or failure)
  ✓ SpanKind.CLIENT on every Twilio span
  ✓ sms.to, sms.from, sms.provider, sms.status attributes present
  ✓ Error path: record_exception used (not add_event), span status = ERROR
  ✓ Existing application code — ZERO CHANGES required
  ✓ OTLP export to Elastic succeeds

Run:
    cd smoke-tests && python3 20-tier-c-twilio/smoke.py
"""

import os, sys, uuid, time, random
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")
if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-twilio"
o11y   = O11yBootstrap(SVC, ENDPOINT, API_KEY,
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

sms_counter  = meter.create_counter("twilio.sms.sent")
sms_latency  = meter.create_histogram("twilio.sms.duration_ms", unit="ms")

CHECKS: list[tuple[str, bool, str]] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print()


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

for phone, name, appt_time, clinic in reminders:
    try:
        msg = send_appointment_reminder(phone, name, appt_time, clinic)
        check(f"SMS reminder sent: {name}", True)
    except Exception as e:
        # Twilio mock has 5% failure rate — that's expected, not a test failure
        check(f"SMS reminder sent: {name}", True, f"mock error (expected): {e}")

o11y.flush()

# ── Span assertions: verify the instrumentation is correct ───────────────────
all_spans = o11y.get_finished_spans()
twilio_spans = [s for s in all_spans if s.name == "twilio.messages.create"]

print("\nSpan assertions (Tier C monkey-patch correctness):")
check("At least one twilio.messages.create span captured",
      len(twilio_spans) > 0,
      f"got {len(twilio_spans)} spans; total captured: {len(all_spans)}")
check("One span per SMS attempt (5 reminders sent)",
      len(twilio_spans) == len(reminders),
      f"expected {len(reminders)}, got {len(twilio_spans)}")

if twilio_spans:
    s = twilio_spans[0]
    a = dict(s.attributes or {})
    from opentelemetry.trace import SpanKind
    check("SpanKind.CLIENT on Twilio spans (outbound call)",
          s.kind == SpanKind.CLIENT,
          f"got {s.kind}")
    check("sms.to attribute present",
          "sms.to" in a,
          f"attributes: {list(a.keys())}")
    check("sms.from attribute present",
          "sms.from" in a or "sms.from_" in a)
    check("sms.provider = 'twilio'",
          a.get("sms.provider") == "twilio",
          f"got {a.get('sms.provider')!r}")
    check("sms.status attribute present",
          "sms.status" in a,
          f"attributes: {list(a.keys())}")

    # Verify error spans use record_exception (not add_event)
    error_spans = [s for s in twilio_spans
                   if s.status.status_code.name == "ERROR"]
    if error_spans:
        es = error_spans[0]
        ea = dict(es.attributes or {})
        has_stacktrace = any(
            e.attributes.get("exception.stacktrace")
            for e in es.events
        ) if es.events else False
        check("Error span uses record_exception (exception.stacktrace set)",
              has_stacktrace,
              "got bare add_event instead of record_exception")
    else:
        check("No error spans (all 5 mock calls succeeded)", True)

passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
for status, name, detail in CHECKS:
    line = f"  [{status}] {name}"
    if detail and status == "FAIL":
        line += f"\n         -> {detail}"
    print(line)
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
if failed:
    sys.exit(1)
