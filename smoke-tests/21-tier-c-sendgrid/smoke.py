#!/usr/bin/env python3
"""
Smoke test: Tier C — SendGrid SDK (monkey-patched).

Patches sendgrid.SendGridAPIClient.send() — existing call sites unchanged.
Business scenario: Password reset flow and welcome email sequence.

Run:
    cd smoke-tests && python3 21-tier-c-sendgrid/smoke.py
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

SVC = "smoke-tier-c-sendgrid"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

email_counter = meter.create_counter("sendgrid.emails.sent")
email_latency = meter.create_histogram("sendgrid.send.duration_ms", unit="ms")


# ── Mock SendGrid SDK ─────────────────────────────────────────────────────────
class _MockResponse:
    def __init__(self):
        self.status_code = 202
        self.headers = {"X-Message-Id": uuid.uuid4().hex}

class _MockSendGridClient:
    def send(self, message):
        time.sleep(0.03)
        if random.random() < 0.03:
            raise Exception("SendGrid API: 429 Too Many Requests")
        return _MockResponse()

class sendgrid:
    SendGridAPIClient = _MockSendGridClient

class Mail:
    def __init__(self, from_email, to_emails, subject, html_content, template_id=None):
        self.from_email   = from_email
        self.to_emails    = to_emails if isinstance(to_emails, list) else [to_emails]
        self.subject      = subject
        self.html_content = html_content
        self.template_id  = template_id


# ── Tier C: patch client.send ────────────────────────────────────────────────
_orig_send = sendgrid.SendGridAPIClient.send

def _instrumented_send(self, message):
    t0 = time.time()
    to_list = getattr(message, "to_emails", ["unknown"])

    with tracer.start_as_current_span("sendgrid.send", kind=SpanKind.CLIENT,
        attributes={"email.to":          str(to_list[0]),
                    "email.subject":     getattr(message, "subject", ""),
                    "email.template_id": getattr(message, "template_id", "") or "",
                    "email.provider":    "sendgrid"}) as span:
        try:
            resp = _orig_send(self, message)
            dur  = (time.time() - t0) * 1000
            msg_id = resp.headers.get("X-Message-Id", "")
            span.set_attribute("email.status_code",   resp.status_code)
            span.set_attribute("email.message_id",    msg_id)
            email_counter.add(1, attributes={"email.status": "sent",
                                              "email.template": getattr(message, "template_id", "custom") or "custom"})
            email_latency.record(dur, attributes={"email.status": "sent"})
            logger.info("email sent via sendgrid",
                        extra={"email.to": str(to_list[0]), "email.message_id": msg_id,
                               "email.subject": getattr(message, "subject", ""),
                               "sendgrid.status_code": resp.status_code})
            return resp
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            email_counter.add(1, attributes={"email.status": "failed"})
            logger.error("sendgrid send failed",
                         extra={"email.to": str(to_list[0]), "error.message": str(e)})
            raise

sendgrid.SendGridAPIClient.send = _instrumented_send   # ← one-line patch


# ── Existing application code — ZERO CHANGES ─────────────────────────────────
def send_password_reset(user_email):
    sg = sendgrid.SendGridAPIClient()
    msg = Mail(
        from_email="noreply@company.com",
        to_emails=user_email,
        subject="Reset your password",
        html_content="<p>Click here to reset your password.</p>",
        template_id="d-password-reset-v2",
    )
    return sg.send(msg)

def send_welcome_email(user_email, plan):
    sg = sendgrid.SendGridAPIClient()
    msg = Mail(
        from_email="welcome@company.com",
        to_emails=user_email,
        subject=f"Welcome to your {plan} plan!",
        html_content=f"<p>Welcome! You're now on the {plan} plan.</p>",
        template_id="d-welcome-v3",
    )
    return sg.send(msg)


print(f"\n[{SVC}] Sending emails via patched SendGrid SDK...")
for email in ["alice@enterprise.com", "bob@startup.io", "carol@personal.net"]:
    try:
        resp = send_password_reset(email)
        print(f"  ✅ password-reset  {email:<30}  status={resp.status_code}")
    except Exception as e:
        print(f"  🚫 password-reset  {email:<30}  error={e}")

for email, plan in [("dave@bigcorp.com", "enterprise"), ("eve@smallbiz.com", "pro")]:
    try:
        resp = send_welcome_email(email, plan)
        print(f"  ✅ welcome-{plan:<12}{email:<30}  status={resp.status_code}")
    except Exception as e:
        print(f"  🚫 welcome-{plan:<12}{email:<30}  error={e}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
