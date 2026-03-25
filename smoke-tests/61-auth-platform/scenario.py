#!/usr/bin/env python3
"""
Auth & Identity Platform — Distributed Tracing Scenario
========================================================

Services modeled:
  api-gateway → auth-service → user-directory
                             → mfa-service
                → token-service
                → session-store
                → audit-service

25 trace scenarios with realistic error mix:
  55% successful login
  15% wrong password (1-2 attempts, or lockout after 3)
  10% account locked
   8% MFA timeout
   7% suspicious login (step-up auth)
   5% token expired (refresh flow)

Run:
    cd smoke-tests
    python3 61-auth-platform/scenario.py
"""

import os, sys, uuid, time, random, ipaddress
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
gateway   = O11yBootstrap("api-gateway",    ENDPOINT, API_KEY, ENV)
auth      = O11yBootstrap("auth-service",   ENDPOINT, API_KEY, ENV)
directory = O11yBootstrap("user-directory", ENDPOINT, API_KEY, ENV)
mfa       = O11yBootstrap("mfa-service",    ENDPOINT, API_KEY, ENV)
tokens    = O11yBootstrap("token-service",  ENDPOINT, API_KEY, ENV)
sessions  = O11yBootstrap("session-store",  ENDPOINT, API_KEY, ENV)
audit     = O11yBootstrap("audit-service",  ENDPOINT, API_KEY, ENV)

# ── Metrics instruments ───────────────────────────────────────────────────────
gw_requests     = gateway.meter.create_counter("gateway.requests",           description="Total gateway requests")
gw_latency      = gateway.meter.create_histogram("gateway.duration_ms",      description="Gateway request latency", unit="ms")

auth_attempts   = auth.meter.create_counter("auth.attempts",                 description="Authentication attempts")
auth_failures   = auth.meter.create_counter("auth.failures",                 description="Authentication failures by reason")
auth_latency    = auth.meter.create_histogram("auth.duration_ms",            description="Auth flow latency", unit="ms")

dir_lookups     = directory.meter.create_counter("directory.lookups",        description="User directory lookups")
dir_latency     = directory.meter.create_histogram("directory.lookup_ms",    description="Directory lookup latency", unit="ms")

mfa_challenges  = mfa.meter.create_counter("mfa.challenges",                 description="MFA challenges issued")
mfa_timeouts    = mfa.meter.create_counter("mfa.timeouts",                   description="MFA timeouts")
mfa_latency     = mfa.meter.create_histogram("mfa.duration_ms",              description="MFA verification latency", unit="ms")

token_issued    = tokens.meter.create_counter("token.issued",                description="Tokens issued")
token_refreshed = tokens.meter.create_counter("token.refreshed",             description="Token refresh operations")

session_active  = sessions.meter.create_counter("session.created",           description="Sessions created")
session_expired = sessions.meter.create_counter("session.expired",           description="Sessions expired/revoked")

suspicious_logins = gateway.meter.create_counter("auth.suspicious_logins",   description="Suspicious login events detected")


# ── User profiles ─────────────────────────────────────────────────────────────
USERS = [
    {"id": "USR-001", "email": "alice@corp.com",      "dept": "Engineering",  "status": "active",  "mfa_type": "totp",    "failed_attempts": 0, "known_ips": ["10.0.1.5", "192.168.1.100"]},
    {"id": "USR-002", "email": "bob@corp.com",         "dept": "Finance",      "status": "active",  "mfa_type": "sms",     "failed_attempts": 0, "known_ips": ["10.0.2.11"]},
    {"id": "USR-003", "email": "carol@corp.com",       "dept": "Marketing",    "status": "active",  "mfa_type": "push",    "failed_attempts": 1, "known_ips": ["172.16.0.50"]},
    {"id": "USR-004", "email": "david@corp.com",       "dept": "HR",           "status": "active",  "mfa_type": "totp",    "failed_attempts": 2, "known_ips": ["10.0.3.20"]},
    {"id": "USR-005", "email": "eve@corp.com",         "dept": "Engineering",  "status": "active",  "mfa_type": "totp",    "failed_attempts": 0, "known_ips": ["10.0.1.99", "192.168.2.5"]},
    {"id": "USR-006", "email": "frank@corp.com",       "dept": "Legal",        "status": "locked",  "mfa_type": "sms",     "failed_attempts": 3, "known_ips": ["10.0.4.7"]},
    {"id": "USR-007", "email": "grace@corp.com",       "dept": "Sales",        "status": "active",  "mfa_type": "push",    "failed_attempts": 0, "known_ips": ["172.16.1.5"]},
    {"id": "USR-008", "email": "hank@corp.com",        "dept": "DevOps",       "status": "locked",  "mfa_type": "totp",    "failed_attempts": 5, "known_ips": ["10.0.5.3"]},
    {"id": "USR-009", "email": "iris@corp.com",        "dept": "Product",      "status": "active",  "mfa_type": "totp",    "failed_attempts": 0, "known_ips": ["10.0.6.44"]},
    {"id": "USR-010", "email": "jack@corp.com",        "dept": "Engineering",  "status": "active",  "mfa_type": "sms",     "failed_attempts": 0, "known_ips": ["10.0.1.200", "10.0.7.8"]},
    {"id": "USR-011", "email": "karen@corp.com",       "dept": "Design",       "status": "active",  "mfa_type": "push",    "failed_attempts": 0, "known_ips": ["172.16.2.10"]},
    {"id": "USR-012", "email": "liam@corp.com",        "dept": "Finance",      "status": "active",  "mfa_type": "totp",    "failed_attempts": 1, "known_ips": ["10.0.2.55"]},
    {"id": "USR-013", "email": "mia@external.com",     "dept": "Contractor",   "status": "active",  "mfa_type": "totp",    "failed_attempts": 0, "known_ips": ["203.0.113.45"]},
    {"id": "USR-014", "email": "noah@corp.com",        "dept": "Engineering",  "status": "active",  "mfa_type": "totp",    "failed_attempts": 0, "known_ips": ["10.0.1.77"]},
    {"id": "USR-015", "email": "olivia@corp.com",      "dept": "Sales",        "status": "active",  "mfa_type": "sms",     "failed_attempts": 0, "known_ips": ["172.16.3.20"]},
]

DEVICE_TYPES = ["desktop", "mobile", "tablet", "laptop"]
DEVICE_OS    = ["macOS 14", "Windows 11", "iOS 17", "Android 14", "Ubuntu 22.04", "ChromeOS"]
IP_COUNTRIES = ["US", "GB", "DE", "FR", "IN", "CA", "AU", "JP"]
VPN_IPS      = ["185.220.101.5", "195.181.170.9", "37.19.200.5", "104.244.76.13"]
SUSPICIOUS_IPS = ["94.102.49.190", "91.108.4.200", "176.9.88.15"]

AUTH_METHODS = ["password", "oauth", "saml"]


# ── Helper ─────────────────────────────────────────────────────────────────────
def inject_traceparent(span) -> str:
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"

def extract_context(tp: str):
    return propagator.extract({"traceparent": tp})

def random_ip(user: dict, suspicious: bool = False, vpn: bool = False) -> tuple:
    if suspicious:
        ip = random.choice(SUSPICIOUS_IPS)
        return ip, random.choice(IP_COUNTRIES), True
    if vpn:
        ip = random.choice(VPN_IPS)
        return ip, random.choice(IP_COUNTRIES), True
    if random.random() < 0.7 and user["known_ips"]:
        ip = random.choice(user["known_ips"])
        return ip, "US", False
    # Unknown IP
    ip = f"198.51.{random.randint(1,254)}.{random.randint(1,254)}"
    return ip, random.choice(IP_COUNTRIES), False


# ── Service functions ──────────────────────────────────────────────────────────

def svc_user_directory(request_id: str, user: dict, parent_tp: str,
                        force_locked: bool = False) -> tuple:
    """Look up user in directory (LDAP/DB)."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with auth.tracer.start_as_current_span(
        "http.client.user_directory", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "GET", "net.peer.name": "user-directory",
                    "http.url": f"http://user-directory/api/v1/users/{user['id']}",
                    "request.id": request_id, "user.id": user["id"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with directory.tracer.start_as_current_span(
            "directory.lookup_user", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "GET", "http.route": "/api/v1/users/{id}",
                        "request.id": request_id, "user.id": user["id"],
                        "user.email": user["email"], "directory.backend": "ldap+postgresql",
                        "directory.cache": "redis-cluster"}
        ) as entry_span:
            time.sleep(random.uniform(0.02, 0.08))

            status = "LOCKED" if (force_locked or user["status"] == "locked") else "ACTIVE"
            entry_span.set_attribute("user.status",      status)
            entry_span.set_attribute("user.department",  user["dept"])
            entry_span.set_attribute("user.mfa_enabled", True)
            entry_span.set_attribute("user.mfa_type",    user["mfa_type"])
            entry_span.set_attribute("user.failed_attempts", user["failed_attempts"])

            dur_ms = (time.time() - t0) * 1000
            dir_lookups.add(1, attributes={"user.status": status})
            dir_latency.record(dur_ms, attributes={"directory.backend": "ldap+postgresql"})

            if status == "LOCKED":
                entry_span.record_exception(PermissionError("Account locked"), attributes={"exception.escaped": True})
                entry_span.set_status(StatusCode.ERROR, "Account locked")
                directory.logger.warning(
                    f"user lookup: account locked for {user['email']}",
                    extra={"request.id": request_id, "user.id": user["id"],
                           "user.status": status, "user.failed_attempts": user["failed_attempts"]}
                )
            else:
                directory.logger.info(
                    f"user lookup successful: {user['email']}",
                    extra={"request.id": request_id, "user.id": user["id"],
                           "user.department": user["dept"], "user.status": status}
                )
            return status, inject_traceparent(entry_span)


def svc_mfa(request_id: str, user: dict, parent_tp: str,
             force_timeout: bool = False) -> tuple:
    """Issue and verify MFA challenge."""
    parent_ctx = extract_context(parent_tp)
    challenge_id = f"MFA-{uuid.uuid4().hex[:8].upper()}"
    t0 = time.time()

    with auth.tracer.start_as_current_span(
        "http.client.mfa_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "mfa-service",
                    "http.url": "http://mfa-service/api/v2/challenge",
                    "request.id": request_id, "auth.mfa_type": user["mfa_type"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with mfa.tracer.start_as_current_span(
            "mfa.issue_challenge", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v2/challenge",
                        "request.id": request_id, "user.id": user["id"],
                        "auth.mfa_type": user["mfa_type"],
                        "mfa.challenge_id": challenge_id,
                        "mfa.provider": "duo-security" if user["mfa_type"] == "push" else "internal-totp"}
        ) as entry_span:
            time.sleep(random.uniform(0.03, 0.09))
            mfa_challenges.add(1, attributes={"auth.mfa_type": user["mfa_type"]})
            mfa.logger.info(
                f"MFA challenge issued: {challenge_id}",
                extra={"request.id": request_id, "user.id": user["id"],
                       "mfa.challenge_id": challenge_id, "auth.mfa_type": user["mfa_type"]}
            )

            # Simulate user response time
            if force_timeout:
                time.sleep(random.uniform(3.0, 5.0))  # user didn't respond in time
                err = Exception(f"MFATimeoutError: challenge {challenge_id} expired after 300s")
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                exit_span.record_exception(TimeoutError(f"MFA challenge {challenge_id} timed out"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "mfa_timeout")
                mfa_timeouts.add(1, attributes={"auth.mfa_type": user["mfa_type"]})
                mfa.logger.warning(
                    f"MFA timeout: challenge {challenge_id} expired",
                    extra={"request.id": request_id, "user.id": user["id"],
                           "mfa.challenge_id": challenge_id, "auth.mfa_type": user["mfa_type"],
                           "mfa.timeout_seconds": 300}
                )
                raise err

            time.sleep(random.uniform(0.5, 2.0))  # user response time
            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("mfa.verified", True)
            entry_span.set_attribute("mfa.verification_ms", round(dur_ms, 2))
            mfa_latency.record(dur_ms, attributes={"auth.mfa_type": user["mfa_type"], "result": "success"})

            mfa.logger.info(
                f"MFA verified: {challenge_id} ({user['mfa_type']})",
                extra={"request.id": request_id, "user.id": user["id"],
                       "mfa.challenge_id": challenge_id, "mfa.verification_ms": round(dur_ms, 2)}
            )
            return True, inject_traceparent(entry_span)


def svc_token_service(request_id: str, user: dict, session_id: str,
                       parent_tp: str, is_refresh: bool = False) -> tuple:
    """Issue JWT access + refresh tokens."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with auth.tracer.start_as_current_span(
        "http.client.token_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "token-service",
                    "http.url": "http://token-service/api/v1/token",
                    "request.id": request_id, "token.operation": "refresh" if is_refresh else "issue"}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with tokens.tracer.start_as_current_span(
            "token.issue_jwt", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/token",
                        "request.id": request_id, "user.id": user["id"],
                        "token.operation": "refresh" if is_refresh else "issue",
                        "token.algorithm": "RS256",
                        "token.access_ttl_seconds": 3600,
                        "token.refresh_ttl_seconds": 86400 * 7,
                        "session.id": session_id}
        ) as entry_span:
            time.sleep(random.uniform(0.01, 0.04))

            access_token  = f"eyJ.{uuid.uuid4().hex[:32]}.{uuid.uuid4().hex[:16]}"
            refresh_token = f"rt_{uuid.uuid4().hex[:48]}"

            entry_span.set_attribute("token.access_token_prefix",  access_token[:20])
            entry_span.set_attribute("token.refresh_issued",       True)
            entry_span.set_attribute("token.scope",                "read write profile")

            dur_ms = (time.time() - t0) * 1000
            if is_refresh:
                token_refreshed.add(1, attributes={"user.department": user["dept"]})
                tokens.logger.info(
                    f"token refreshed for user {user['id']}",
                    extra={"request.id": request_id, "user.id": user["id"],
                           "session.id": session_id, "token.operation": "refresh"}
                )
            else:
                token_issued.add(1, attributes={"user.department": user["dept"]})
                tokens.logger.info(
                    f"token issued for user {user['id']}",
                    extra={"request.id": request_id, "user.id": user["id"],
                           "session.id": session_id, "token.algorithm": "RS256",
                           "token.scope": "read write profile"}
                )
            return access_token, refresh_token, inject_traceparent(entry_span)


def svc_session_store(request_id: str, user: dict, ip: str, device: str,
                       parent_tp: str, action: str = "create") -> tuple:
    """Redis session management."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()
    session_id = f"sess_{uuid.uuid4().hex[:32]}"

    with auth.tracer.start_as_current_span(
        "redis.client.session_store", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"db.system": "redis", "net.peer.name": "session-store",
                    "db.redis.database_index": 1, "db.operation": action.upper(),
                    "request.id": request_id, "session.action": action}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with sessions.tracer.start_as_current_span(
            f"session.{action}", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"db.system": "redis", "db.operation": action.upper(),
                        "request.id": request_id, "session.id": session_id,
                        "user.id": user["id"], "session.ip": ip,
                        "session.device": device, "session.ttl_seconds": 28800,
                        "session.store": "redis-cluster-6379"}
        ) as entry_span:
            time.sleep(random.uniform(0.005, 0.02))

            entry_span.set_attribute("session.id",        session_id)
            entry_span.set_attribute("session.created_at", int(time.time()))

            if action == "create":
                session_active.add(1, attributes={"user.department": user["dept"]})
                sessions.logger.info(
                    f"session created: {session_id[:16]}... for user {user['id']}",
                    extra={"request.id": request_id, "session.id": session_id,
                           "user.id": user["id"], "session.ip": ip, "session.device": device}
                )

            return session_id, inject_traceparent(entry_span)


def svc_audit(request_id: str, user: dict, event_type: str,
               ip: str, ip_country: str, is_vpn: bool,
               auth_method: str, result: str,
               parent_tp: str, extra_attrs: dict = None) -> None:
    """Append security event to audit log."""
    parent_ctx = extract_context(parent_tp)

    with gateway.tracer.start_as_current_span(
        "http.client.audit_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "audit-service",
                    "http.url": "http://audit-service/api/v1/events",
                    "request.id": request_id, "audit.event_type": event_type}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with audit.tracer.start_as_current_span(
            "audit.record_event", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/events",
                        "request.id": request_id, "audit.event_type": event_type,
                        "user.id": user["id"], "user.email": user["email"],
                        "user.department": user["dept"],
                        "auth.method": auth_method, "auth.result": result,
                        "ip.address": ip, "ip.country": ip_country,
                        "ip.is_vpn": is_vpn, "audit.backend": "elasticsearch",
                        **(extra_attrs or {})}
        ) as entry_span:
            time.sleep(random.uniform(0.01, 0.03))

            audit_event_id = f"EVT-{uuid.uuid4().hex[:12].upper()}"
            entry_span.set_attribute("audit.event_id",    audit_event_id)
            entry_span.set_attribute("audit.indexed",     True)

            level = "WARNING" if result != "success" else "INFO"
            log_fn = audit.logger.warning if result != "success" else audit.logger.info
            log_fn(
                f"security event: {event_type} user={user['email']} result={result} ip={ip}",
                extra={"request.id": request_id, "audit.event_id": audit_event_id,
                       "audit.event_type": event_type, "user.id": user["id"],
                       "ip.address": ip, "ip.country": ip_country, "ip.is_vpn": is_vpn,
                       "auth.result": result, "auth.method": auth_method}
            )


def run_auth_flow(scenario: str, user: dict, auth_method: str,
                   ip: str, ip_country: str, is_vpn: bool,
                   device_type: str, device_os: str,
                   force_wrong_pw: bool = False, force_locked: bool = False,
                   force_mfa_timeout: bool = False, is_refresh: bool = False,
                   is_suspicious: bool = False, attempt_num: int = 1) -> bool:
    """Full authentication flow orchestrated by api-gateway."""
    request_id = f"REQ-{uuid.uuid4().hex[:12].upper()}"
    t_start    = time.time()

    print(f"\n  [{scenario}] user={user['email']} method={auth_method} "
          f"ip={ip} ({ip_country}) vpn={is_vpn}")

    with gateway.tracer.start_as_current_span(
        "gateway.auth_request", kind=SpanKind.SERVER,
        attributes={"http.method": "POST", "http.route": "/api/v1/auth/login",
                    "request.id": request_id, "user.email": user["email"],
                    "auth.method": auth_method, "ip.address": ip,
                    "ip.country": ip_country, "ip.is_vpn": is_vpn,
                    "device.type": device_type, "device.os": device_os,
                    "login.attempt_number": attempt_num,
                    "scenario": scenario}
    ) as root_span:
        tp_root = inject_traceparent(root_span)
        gw_requests.add(1, attributes={"auth.method": auth_method})

        try:
            # Suspicious login: flag before proceeding
            if is_suspicious or is_vpn:
                root_span.set_attribute("auth.suspicious", True)
                root_span.set_attribute("auth.step_up_required", True)
                suspicious_logins.add(1, attributes={"ip.country": ip_country})
                gateway.logger.warning(
                    f"suspicious login detected: {user['email']} from {ip} ({ip_country})",
                    extra={"request.id": request_id, "user.email": user["email"],
                           "ip.address": ip, "ip.country": ip_country,
                           "ip.is_vpn": is_vpn, "auth.suspicious": True}
                )

            # Token refresh flow — different path
            if is_refresh:
                session_id, tp_sess = svc_session_store(
                    request_id, user, ip, device_type, tp_root, action="validate")
                access_token, refresh_token, tp_tok = svc_token_service(
                    request_id, user, session_id, tp_root, is_refresh=True)
                svc_audit(request_id, user, "token_refresh", ip, ip_country, is_vpn,
                           auth_method, "success", tp_root)
                dur_ms = (time.time() - t_start) * 1000
                gw_latency.record(dur_ms, attributes={"result": "token_refreshed"})
                root_span.set_attribute("auth.result", "token_refreshed")
                gateway.logger.info(
                    f"token refresh successful: {user['email']}",
                    extra={"request.id": request_id, "user.id": user["id"],
                           "auth.result": "token_refreshed"}
                )
                print(f"    ✅ Token refreshed for {user['email']}")
                return True

            # Step 1: user directory lookup
            with auth.tracer.start_as_current_span(
                "auth.validate_credentials", kind=SpanKind.SERVER,
                context=extract_context(tp_root),
                attributes={"request.id": request_id, "user.id": user["id"],
                            "auth.method": auth_method, "login.attempt_number": attempt_num}
            ) as auth_span:
                tp_auth = inject_traceparent(auth_span)

                user_status, tp_dir = svc_user_directory(
                    request_id, user, tp_auth, force_locked=force_locked)

                if user_status == "LOCKED":
                    auth_span.record_exception(PermissionError("Account locked"), attributes={"exception.escaped": True})
                    auth_span.set_status(StatusCode.ERROR, "Account locked")
                    root_span.record_exception(PermissionError("Account locked"), attributes={"exception.escaped": True})
                    root_span.set_status(StatusCode.ERROR, "Account locked")
                    auth_failures.add(1, attributes={"auth.failure_reason": "account_locked"})
                    svc_audit(request_id, user, "login_failed", ip, ip_country, is_vpn,
                               auth_method, "account_locked", tp_root)
                    dur_ms = (time.time() - t_start) * 1000
                    gw_latency.record(dur_ms, attributes={"result": "account_locked"})
                    auth.logger.error(
                        f"login rejected: account locked for {user['email']}",
                        extra={"request.id": request_id, "user.id": user["id"],
                               "auth.failure_reason": "account_locked",
                               "user.failed_attempts": user["failed_attempts"]}
                    )
                    print(f"    ❌ Account locked: {user['email']} ({user['failed_attempts']} failed attempts)")
                    return False

                auth_attempts.add(1, attributes={"auth.method": auth_method})

                # Simulate password validation
                time.sleep(random.uniform(0.03, 0.08))

                if force_wrong_pw:
                    auth_span.record_exception(PermissionError("Invalid credentials"), attributes={"exception.escaped": True})
                    auth_span.set_status(StatusCode.ERROR, "Invalid credentials")
                    root_span.record_exception(PermissionError("Invalid credentials"), attributes={"exception.escaped": True})
                    root_span.set_status(StatusCode.ERROR, "Invalid credentials")
                    auth_failures.add(1, attributes={"auth.failure_reason": "invalid_password"})
                    svc_audit(request_id, user, "login_failed", ip, ip_country, is_vpn,
                               auth_method, "invalid_password", tp_root,
                               {"login.attempt_number": attempt_num})
                    dur_ms = (time.time() - t_start) * 1000
                    gw_latency.record(dur_ms, attributes={"result": "invalid_credentials"})
                    auth.logger.warning(
                        f"invalid password: {user['email']} attempt {attempt_num}",
                        extra={"request.id": request_id, "user.id": user["id"],
                               "login.attempt_number": attempt_num,
                               "auth.failure_reason": "invalid_password"}
                    )
                    print(f"    ❌ Wrong password: {user['email']} (attempt {attempt_num})")
                    return False

                auth_span.set_attribute("auth.password_verified", True)

            # Step 2: MFA challenge
            mfa_ok, tp_mfa = svc_mfa(
                request_id, user, tp_root, force_timeout=force_mfa_timeout)

            # Step 3: create session
            session_id, tp_sess = svc_session_store(
                request_id, user, ip, device_type, tp_root, action="create")

            # Step 4: issue tokens
            access_token, refresh_token, tp_tok = svc_token_service(
                request_id, user, session_id, tp_root)

            # Step 5: audit trail
            svc_audit(request_id, user, "login_success", ip, ip_country, is_vpn,
                       auth_method, "success", tp_root,
                       {"session.id": session_id, "auth.mfa_type": user["mfa_type"]})

            root_span.set_attribute("auth.result",     "success")
            root_span.set_attribute("session.id",      session_id)
            root_span.set_attribute("auth.mfa_verified", True)

            dur_ms = (time.time() - t_start) * 1000
            gw_latency.record(dur_ms, attributes={"result": "success"})
            auth_latency.record(dur_ms, attributes={"auth.method": auth_method})

            gateway.logger.info(
                f"login successful: {user['email']} session={session_id[:16]}...",
                extra={"request.id": request_id, "user.id": user["id"],
                       "session.id": session_id, "auth.method": auth_method,
                       "auth.mfa_type": user["mfa_type"], "ip.address": ip,
                       "ip.country": ip_country, "auth.duration_ms": dur_ms}
            )
            tag = "⚠️" if is_suspicious or is_vpn else "✅"
            print(f"    {tag} Login {'(suspicious IP flagged) ' if is_suspicious else ''}success: "
                  f"{user['email']} session={session_id[:16]}...")
            return True

        except Exception as e:
            root_span.record_exception(e)
            root_span.set_status(StatusCode.ERROR, str(e))
            dur_ms = (time.time() - t_start) * 1000
            gw_latency.record(dur_ms, attributes={"result": "error"})
            auth_failures.add(1, attributes={"auth.failure_reason": type(e).__name__})
            svc_audit(request_id, user, "login_error", ip, ip_country, is_vpn,
                       auth_method, "error", tp_root)
            gateway.logger.error(
                f"auth flow error: {e}",
                extra={"request.id": request_id, "user.id": user["id"],
                       "error.type": type(e).__name__, "error.message": str(e)}
            )
            print(f"    ❌ Auth error: {e}")
            return False


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print("  Auth & Identity Platform — Distributed Tracing Demo")
    print("  Services: api-gateway → auth-service → user-directory")
    print("            → mfa-service → token-service → session-store → audit-service")
    print(f"{'='*70}")

    # 25 scenarios: 14 success, 4 wrong_pw, 3 locked, 2 mfa_timeout, 1 suspicious, 1 refresh
    scenario_pool = (
        ["success"] * 14 +
        ["wrong_password"] * 4 +
        ["account_locked"] * 3 +
        ["mfa_timeout"] * 2 +
        ["suspicious_login"] * 1 +
        ["token_refresh"] * 1
    )
    random.shuffle(scenario_pool)

    stats = {"success": 0, "wrong_password": 0, "locked": 0,
             "mfa_timeout": 0, "suspicious": 0, "refresh": 0, "total": 0}

    for i, scenario in enumerate(scenario_pool):
        user        = random.choice(USERS)
        method      = random.choice(AUTH_METHODS)
        device_type = random.choice(DEVICE_TYPES)
        device_os   = random.choice(DEVICE_OS)

        # Choose scenario-specific overrides
        force_wrong_pw    = scenario == "wrong_password"
        force_locked      = scenario == "account_locked"
        force_mfa_timeout = scenario == "mfa_timeout"
        is_suspicious     = scenario == "suspicious_login"
        is_refresh        = scenario == "token_refresh"

        if force_locked:
            user = next((u for u in USERS if u["status"] == "locked"), USERS[5])
        elif is_suspicious:
            ip, country, is_vpn = random_ip(user, suspicious=True)
        else:
            ip, country, is_vpn = random_ip(user, vpn=(random.random() < 0.15))

        if not is_suspicious:
            ip, country, is_vpn = random_ip(user, vpn=(random.random() < 0.1))

        print(f"\n{'─'*70}")
        print(f"  Scenario {i+1:02d}/25  [{scenario}]")

        result = run_auth_flow(
            scenario, user, method, ip, country, is_vpn,
            device_type, device_os,
            force_wrong_pw=force_wrong_pw,
            force_locked=force_locked,
            force_mfa_timeout=force_mfa_timeout,
            is_refresh=is_refresh,
            is_suspicious=is_suspicious,
        )
        stats["total"] += 1
        if result:
            if is_refresh: stats["refresh"] += 1
            else: stats["success"] += 1
        elif force_wrong_pw:   stats["wrong_password"] += 1
        elif force_locked:     stats["locked"] += 1
        elif force_mfa_timeout:stats["mfa_timeout"] += 1
        elif is_suspicious:    stats["suspicious"] += 1

        time.sleep(random.uniform(0.1, 0.25))

    print(f"\n{'='*70}")
    print("  Flushing all telemetry providers...")
    for svc in [gateway, auth, directory, mfa, tokens, sessions, audit]:
        svc.flush()

    print(f"\n  Results: {stats['total']} scenarios")
    print(f"    ✅ Success:         {stats['success']}")
    print(f"    🔄 Token refresh:   {stats['refresh']}")
    print(f"    ❌ Wrong password:  {stats['wrong_password']}")
    print(f"    🔒 Account locked:  {stats['locked']}")
    print(f"    ⏱️  MFA timeout:     {stats['mfa_timeout']}")
    print(f"    ⚠️  Suspicious:      {stats['suspicious']}")

    print(f"\n  Kibana:")
    print(f"    Service Map → Observability → APM → Service Map")
    print(f"    Filter: api-gateway (7 connected nodes expected)")
    print(f"\n  ES|QL query:")
    print(f'    FROM traces-apm*,logs-*')
    print(f'    | WHERE service.name IN ("api-gateway","auth-service","user-directory",')
    print(f'        "mfa-service","token-service","session-store","audit-service")')
    print(f'    | SORT @timestamp DESC | LIMIT 100')
    print(f"{'='*70}\n")
