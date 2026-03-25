#!/usr/bin/env python3
"""
Smoke test: Mobile — Android Kotlin (SecureBank)

Simulates a Galaxy S23 Ultra banking app built with Kotlin + Jetpack Compose.
Uses the EDOT Android SDK (co.elastic.otel.android.agent) — ElasticApmAgent.builder().build().
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 68-mobile-android-kotlin/smoke.py
"""

import hashlib
import os, sys, time, random, uuid
import uuid as _uuid
from pathlib import Path

# EDOT Android automatically generates and attaches session.id to all signals.
# Sessions expire after 30 min of inactivity, max 4 hours.
# Remotely configurable via Kibana central config (v1.2+).
EDOT_SESSION_ID = str(_uuid.uuid4())

# Load .env
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

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")
SVC      = "mobile-android-bankapp"

android = O11yBootstrap(
    SVC, ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        # EDOT Android — Gradle plugin: id("co.elastic.otel.android.agent")
        # Init: ElasticApmAgent.builder(application)
        #   .setServiceName("SecureBank").setExportUrl(url)
        #   .setExportAuthentication(Authentication.ApiKey(key)).build()
        "telemetry.sdk.name":       "opentelemetry-android",  # base SDK (EDOT wraps this)
        "telemetry.sdk.version":    "0.6.0",
        "telemetry.sdk.language":   "java",
        "telemetry.distro.name":    "elastic",                # EDOT-specific
        "telemetry.distro.version": "1.2.0",                  # EDOT Android latest
        "os.type":        "linux",
        "os.name":        "Android",
        "os.version":     "13.0",
        "os.description": "Android 13 (API 33, build UE1A.230829.036)",
        "os.build_id":    "UE1A.230829.036",
        "device.manufacturer":     "Samsung",
        "device.model.name":       "Galaxy S23 Ultra",
        "device.model.identifier": "SM-S918B",
        "android.api_level":       33,
        "app.name":    "SecureBank",
        "app.version": "5.1.3",
    },
)

# ── Metrics ───────────────────────────────────────────────────────────────────
cold_start_hist    = android.meter.create_histogram("app.cold_start_ms", description="App cold start duration", unit="ms")
recompose_counter  = android.meter.create_counter("compose.recomposition_count", description="Compose recomposition count")
nfc_txn_hist       = android.meter.create_histogram("nfc.transaction_value_usd", description="NFC transaction value", unit="USD")
anr_counter        = android.meter.create_counter("anr.count", description="ANR near-miss count")

results = []

print(f"\n{'='*60}")
print("EDOT-Autopilot | 68-mobile-android-kotlin | EDOT Android SDK v1.2.0")
print("Simulates co.elastic.otel.android.agent — ElasticApmAgent.builder().build()")
print(f"{'='*60}")

# ── Scenario 1: EDOT Android agent initialization ─────────────────────────────
def scen_edot_agent_init():
    """EDOT Android: Gradle plugin bytecode-weaves the app; ElasticApmAgent.builder().build() runs in Application.onCreate()."""
    with android.tracer.start_as_current_span("Application.onCreate", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id",                      EDOT_SESSION_ID)
        span.set_attribute("edot.agent.config.export_url",    "https://<deployment>.apm.<region>.cloud.es.io")
        span.set_attribute("edot.agent.config.auth",          "ApiKey")
        span.set_attribute("edot.agent.config.export_protocol", "otlp/http")
        span.set_attribute("edot.instrumentation.okhttp",     True)   # co.elastic.otel.android.instrumentation.okhttp
        span.set_attribute("edot.instrumentation.otel_adapter", True) # co.elastic.otel.android.instrumentation.oteladapter
        span.set_attribute("edot.disk_buffering.enabled",     True)
        span.set_attribute("edot.central_config.enabled",     True)   # Kibana central config v1.2+
        span.set_attribute("edot.session.sample_rate",        1.0)
        span.set_attribute("startup.type",                    "cold")
        span.set_attribute("app.cold_start_ms",               312)

        # EDOT Android bytecode-weaves Activity lifecycle automatically (via OTel Android adapter)
        with android.tracer.start_as_current_span("Activity.onCreate", kind=SpanKind.INTERNAL) as act:
            act.set_attribute("session.id",        EDOT_SESSION_ID)
            act.set_attribute("activity.name",     "MainActivity")
            act.set_attribute("activity.event",    "onCreate")

        with android.tracer.start_as_current_span("Activity.onResume", kind=SpanKind.INTERNAL) as act:
            act.set_attribute("session.id",        EDOT_SESSION_ID)
            act.set_attribute("activity.name",     "MainActivity")
            act.set_attribute("activity.event",    "onResume")
            act.set_attribute("activity.render_ms", 24)

        android.logger.info("EDOT Android agent initialized", extra={
            "session.id":       EDOT_SESSION_ID,
            "edot_version":     "1.2.0",
            "cold_start_ms":    312,
            "startup_type":     "cold",
        })

    # cold start metric
    android.meter.create_histogram(
        "app.cold_start_ms",
        description="Time from process start to first frame drawn",
        unit="ms"
    ).record(312, {"startup.type": "cold", "os.type": "linux"})

try:
    scen_edot_agent_init()
    results.append(("EDOT Android agent init: Application.onCreate + Activity lifecycle", "OK", None))
except Exception as e:
    results.append(("EDOT Android agent init: Application.onCreate + Activity lifecycle", "ERROR", str(e)))

# ── Scenario 2: Jetpack Compose recomposition ─────────────────────────────────
# Compose instrumentation comes via the OTel Android adapter Gradle plugin
# (co.elastic.otel.android.instrumentation.oteladapter), which bytecode-weaves
# Compose recomposition tracking automatically.
try:
    with android.tracer.start_as_current_span("compose.recomposition", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id", EDOT_SESSION_ID)
        span.set_attribute("compose.composable", "AccountDashboard")
        span.set_attribute("compose.recomposition_count", 2)
        recompose_counter.add(2, attributes={"composable": "AccountDashboard"})
        time.sleep(random.uniform(0.05, 0.12))
    android.logger.info("Compose recomposition", extra={
        "session.id":   EDOT_SESSION_ID,
        "composable":   "AccountDashboard",
        "recompositions": 2,
    })
    results.append(("Jetpack Compose recomposition (OTel Android adapter)", "OK", None))
except Exception as e:
    results.append(("Jetpack Compose recomposition", "ERROR", str(e)))

# ── Scenario 3: Biometric unlock + OkHttp auto-span ──────────────────────────
# EDOT Android instruments OkHttp automatically via co.elastic.otel.android.instrumentation.okhttp
try:
    with android.tracer.start_as_current_span("biometric.prompt", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id",            EDOT_SESSION_ID)
        span.set_attribute("biometric.type",        "fingerprint")
        span.set_attribute("biometric.prompt_title", "Authenticate to access SecureBank")
        span.set_attribute("android.activity.name", "LockScreenActivity")
        span.set_attribute("android.fragment.name", "BiometricFragment")
        time.sleep(random.uniform(0.4, 0.9))
        span.set_attribute("biometric.result_code", 1)  # BIOMETRIC_SUCCESS
        span.set_attribute("biometric.result",      "success")

        # EDOT Android: co.elastic.otel.android.instrumentation.okhttp auto-creates this span
        with android.tracer.start_as_current_span("OkHttp.newCall /api/accounts", kind=SpanKind.CLIENT) as http:
            http.set_attribute("session.id",                EDOT_SESSION_ID)
            http.set_attribute("http.request.method",       "GET")
            http.set_attribute("url.full",                  "https://api.securebank.io/v3/accounts")
            http.set_attribute("http.response.status_code", 200)
            http.set_attribute("server.address",            "api.securebank.io")
            http.set_attribute("service.peer.name",         "securebank-api")
            http.set_attribute("okhttp.request.method",     "GET")  # EDOT OkHttp plugin attribute
            http.set_attribute("network.protocol.version",  "2")    # HTTP/2
            http.set_attribute("retrofit.service",          "AccountService")
            http.set_attribute("retrofit.method",           "getAccounts")
            time.sleep(random.uniform(0.08, 0.18))

    android.logger.info("Biometric unlock successful", extra={
        "session.id": EDOT_SESSION_ID,
        "method":     "fingerprint",
    })
    results.append(("Biometric unlock: fingerprint + OkHttp auto-span", "OK", None))
except Exception as e:
    results.append(("Biometric unlock + OkHttp auto-span", "ERROR", str(e)))

# ── Scenario 4: NFC tap-to-pay ────────────────────────────────────────────────
try:
    with android.tracer.start_as_current_span("nfc.payment", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id",            EDOT_SESSION_ID)
        span.set_attribute("android.activity.name", "PaymentActivity")
        span.set_attribute("android.fragment.name", "NFCPaymentFragment")
        span.set_attribute("nfc.technology",        "HCE")  # Host Card Emulation
        span.set_attribute("nfc.aid",               "A0000000031010")  # Visa AID
        txn_amount = round(random.uniform(5.0, 150.0), 2)
        span.set_attribute("payment.amount_usd",    txn_amount)
        span.set_attribute("payment.currency",      "USD")
        span.set_attribute("nfc.terminal_id",       f"TERM-{uuid.uuid4().hex[:6].upper()}")
        time.sleep(random.uniform(0.1, 0.3))  # NFC tap
        with android.tracer.start_as_current_span("OkHttp.newCall /api/payments/authorize", kind=SpanKind.CLIENT) as auth:
            auth.set_attribute("session.id",                EDOT_SESSION_ID)
            auth.set_attribute("http.request.method",       "POST")
            auth.set_attribute("url.full",                  "https://api.securebank.io/v2/payments/authorize")
            auth.set_attribute("server.address",            "api.securebank.io")
            auth.set_attribute("service.peer.name",         "securebank-api")
            auth.set_attribute("okhttp.request.method",     "POST")
            auth.set_attribute("network.protocol.version",  "2")
            time.sleep(random.uniform(0.2, 0.5))
            auth.set_attribute("http.response.status_code", 200)
            auth.set_attribute("payment.authorization_code", uuid.uuid4().hex[:6].upper())
        span.set_attribute("nfc.payment_result", "approved")
        nfc_txn_hist.record(txn_amount, attributes={"payment.method": "nfc_tap"})
    android.logger.info("NFC tap-to-pay complete", extra={
        "session.id": EDOT_SESSION_ID,
        "amount_usd": txn_amount,
        "method":     "HCE",
    })
    results.append(("Payment: NFC tap-to-pay → POS → receipt", "OK", None))
except Exception as e:
    results.append(("Payment: NFC tap-to-pay", "ERROR", str(e)))

# ── Scenario 5: ANR near-miss → offloaded to coroutine ────────────────────────
try:
    with android.tracer.start_as_current_span("anr.detected", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id",             EDOT_SESSION_ID)
        span.set_attribute("android.activity.name",  "MainActivity")
        span.set_attribute("android.fragment.name",  "DashboardFragment")
        span.set_attribute("anr.blocked_thread",     "main")
        span.set_attribute("anr.operation",          "crypto_key_derivation")
        span.set_attribute("anr.blocked_ms_estimate", round(random.uniform(2500, 3900), 0))
        # Simulate near-miss: operation offloaded before 5s threshold
        time.sleep(random.uniform(0.08, 0.2))
        with android.tracer.start_as_current_span("coroutine.offload", kind=SpanKind.INTERNAL) as coroutine:
            coroutine.set_attribute("session.id",           EDOT_SESSION_ID)
            coroutine.set_attribute("coroutine.dispatcher", "Dispatchers.IO")
            coroutine.set_attribute("crypto.algorithm",     "PBKDF2WithHmacSHA256")
            coroutine.set_attribute("crypto.iterations",    100000)
            time.sleep(random.uniform(0.3, 0.7))
        span.set_attribute("anr.resolved",   True)
        span.set_attribute("anr.resolution", "offloaded_to_coroutine")
        anr_counter.add(1, attributes={"anr.resolution": "offloaded_to_coroutine"})
    android.logger.warning("ANR near-miss detected and resolved", extra={
        "session.id": EDOT_SESSION_ID,
        "operation":  "crypto_key_derivation",
        "resolution": "coroutine",
    })
    results.append(("ANR near-miss: main thread blocked → offloaded to coroutine", "WARN", "Resolved before 5s threshold"))
except Exception as e:
    results.append(("ANR near-miss", "ERROR", str(e)))

# ── Scenario 6: NullPointerException crash — EDOT crash report ────────────────
# EDOT Android handles crash reporting via the OTel Android adapter (not Crashlytics bridge)
try:
    with android.tracer.start_as_current_span("compose.recomposition", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id",            EDOT_SESSION_ID)
        span.set_attribute("android.activity.name", "TransactionActivity")
        span.set_attribute("android.fragment.name", "TransactionListFragment")
        span.set_attribute("compose.composable",    "TransactionListItem")
        try:
            time.sleep(random.uniform(0.02, 0.06))
            err = RuntimeError("NullPointerException: Attempt to invoke virtual method on a null object reference in TransactionAdapter.onBindViewHolder")
            span.record_exception(err, attributes={"exception.escaped": False})
            span.set_status(StatusCode.ERROR, str(err))
            span.set_attribute("error.type",              type(err).__name__)
            span.set_attribute("session.id",              EDOT_SESSION_ID)
            span.set_attribute("edot.crash.reported",     True)
            span.set_attribute("edot.crash.reporter",     "elastic-otel-android")  # not Crashlytics bridge
            span.set_attribute("crash.type",              "NullPointerException")
            span.set_attribute("crash.thread",            "main")
            android.logger.error(
                "NPE crash in adapter — reported by EDOT Android crash handler",
                extra={
                    "session.id":  EDOT_SESSION_ID,
                    "crash.type":  "NullPointerException",
                    "composable":  "TransactionListItem",
                },
            )
            results.append(("Crash: NullPointerException in adapter → EDOT crash report", "WARN", "Caught by EDOT crash reporter"))
        except Exception:
            pass
except Exception as e:
    results.append(("Crash: NullPointerException", "ERROR", str(e)))

# ── Metrics: EDOT session counter ─────────────────────────────────────────────
android.meter.create_counter(
    "edot.session.count",
    description="Number of EDOT sessions started",
    unit="{session}",
).add(1, {"os.type": "linux", "app.version": "5.1.3"})

android.flush()

print()
for scenario, status, note in results:
    symbol = "OK" if status == "OK" else ("WARN" if status == "WARN" else "ERROR")
    note_str = f"  ({note})" if note else ""
    print(f"  [{symbol}] {scenario}{note_str}")

ok   = sum(1 for _, s, _ in results if s == "OK")
warn = sum(1 for _, s, _ in results if s == "WARN")
err  = sum(1 for _, s, _ in results if s == "ERROR")
print(f"\n[{SVC}] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → {SVC}")
print("  Metrics: app.cold_start_ms | compose.recomposition_count | nfc.transaction_value_usd | anr.count | edot.session.count")
