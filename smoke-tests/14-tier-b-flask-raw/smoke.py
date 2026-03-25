#!/usr/bin/env python3
"""
Smoke test: Tier B — Flask without EDOT middleware (pre-EDOT legacy app).

Wraps Flask request handlers manually using before/after hooks pattern.
Business scenario: User authentication with MFA — validate credentials,
send OTP via SMS, create session.

Run:
    cd smoke-tests && python3 14-tier-b-flask-raw/smoke.py
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

SVC = "smoke-tier-b-flask-raw"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

auth_counter = meter.create_counter("auth.login_attempts")
mfa_latency  = meter.create_histogram("auth.mfa_duration_ms", unit="ms")
session_ttl  = meter.create_histogram("auth.session_ttl_sec", unit="s")


# ── Tier B: Flask request wrapper (replaces missing EDOT middleware) ──────────
def flask_route_span(method, path, view_func):
    """Wraps a Flask view function — installed once, covers all calls."""
    def wrapped(request_ctx):
        with tracer.start_as_current_span(
            f"{method} {path}", kind=SpanKind.SERVER,
            attributes={"http.method": method, "http.route": path,
                        "http.scheme": "https", "net.peer.ip": request_ctx.get("ip", "127.0.0.1")},
        ) as span:
            try:
                result = view_func(request_ctx)
                span.set_attribute("http.status_code", result.get("status", 200))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
                raise
    return wrapped


# ── Application code — UNCHANGED ─────────────────────────────────────────────
def _validate_credentials(user_id, password_hash):
    """Legacy auth check against user store."""
    with tracer.start_as_current_span("auth.credentials.validate", kind=SpanKind.CLIENT,
        attributes={"auth.user_id": user_id, "auth.method": "password"}) as span:
        time.sleep(0.02)
        valid = password_hash.startswith("hash_")
        span.set_attribute("auth.valid", valid)
        return valid

def _send_otp(user_id, mfa_channel):
    """Send one-time password via chosen channel."""
    t0 = time.time()
    with tracer.start_as_current_span("auth.otp.send", kind=SpanKind.CLIENT,
        attributes={"auth.user_id": user_id, "auth.mfa_channel": mfa_channel}) as span:
        time.sleep(0.05)
        otp_id = f"OTP-{uuid.uuid4().hex[:8].upper()}"
        span.set_attribute("auth.otp_id", otp_id)
        span.set_attribute("auth.otp_sent", True)
        mfa_latency.record((time.time() - t0) * 1000, attributes={"mfa.channel": mfa_channel})
        return otp_id

def login_view(request_ctx):
    user_id       = request_ctx["user_id"]
    password_hash = request_ctx["password_hash"]
    mfa_channel   = request_ctx.get("mfa_channel", "sms")

    valid = _validate_credentials(user_id, password_hash)
    if not valid:
        auth_counter.add(1, attributes={"result": "invalid_credentials", "mfa.channel": mfa_channel})
        logger.warning("login failed: invalid credentials",
                       extra={"auth.user_id": user_id, "auth.method": "password"})
        return {"status": 401, "error": "invalid_credentials"}

    otp_id = _send_otp(user_id, mfa_channel)
    session_id = f"sess_{uuid.uuid4().hex}"
    ttl = 3600

    auth_counter.add(1, attributes={"result": "mfa_pending", "mfa.channel": mfa_channel})
    session_ttl.record(ttl, attributes={"auth.mfa_channel": mfa_channel})

    logger.info("login: MFA OTP dispatched",
                extra={"auth.user_id": user_id, "auth.otp_id": otp_id,
                       "auth.mfa_channel": mfa_channel, "session.id": session_id})
    return {"status": 200, "session_id": session_id, "mfa_required": True, "otp_id": otp_id}


# Wrap the view once at startup
instrumented_login = flask_route_span("POST", "/auth/login", login_view)

login_requests = [
    {"ip": "203.0.113.1", "user_id": "USR-ENT-001", "password_hash": "hash_abc123", "mfa_channel": "sms"},
    {"ip": "203.0.113.2", "user_id": "USR-PRO-042", "password_hash": "hash_xyz789", "mfa_channel": "email"},
    {"ip": "198.51.100.7","user_id": "USR-FREE-007","password_hash": "wrong_pass",  "mfa_channel": "sms"},
    {"ip": "203.0.113.3", "user_id": "USR-ENT-002", "password_hash": "hash_def456", "mfa_channel": "totp"},
]

print(f"\n[{SVC}] Simulating Flask auth endpoint (no EDOT middleware)...")
for req in login_requests:
    result = instrumented_login(req)
    icon = "✅" if result["status"] == 200 else "🚫"
    print(f"  {icon} {req['user_id']}  channel={req['mfa_channel']}  status={result['status']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
