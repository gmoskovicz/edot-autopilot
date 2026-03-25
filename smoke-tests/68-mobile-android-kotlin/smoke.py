#!/usr/bin/env python3
"""
Smoke test: Mobile — Android Kotlin (SecureBank)

Simulates a Galaxy S23 Ultra banking app built with Kotlin + Jetpack Compose.
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 68-mobile-android-kotlin/smoke.py
"""

import hashlib
import os, sys, time, random, uuid
from pathlib import Path

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

o11y = O11yBootstrap(
    SVC, ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        "os.name":                         "Android",
        "os.version":                      "13.0",
        "os.type":                         "linux",
        "os.description":                  "Android 13 (API 33)",
        "device.manufacturer":             "Samsung",
        "device.model.name":               "Galaxy S23 Ultra",
        "device.model.identifier":         "SM-S918B",
        "device.id":                       hashlib.sha256("samsung-s23ultra-uuid-ghi789".encode()).hexdigest()[:16],
        "app.name":                        "SecureBank",
        "app.version":                     "5.1.3",
        "telemetry.sdk.name":              "opentelemetry-android",
        "telemetry.sdk.version":           "0.6.0",
        "telemetry.sdk.language":          "java",
    },
)

tracer = o11y.tracer
logger = o11y.logger
meter  = o11y.meter

# ── Metrics ───────────────────────────────────────────────────────────────────
cold_start_hist    = meter.create_histogram("app.cold_start_ms", description="App cold start duration", unit="ms")
recompose_counter  = meter.create_counter("compose.recomposition_count", description="Compose recomposition count")
nfc_txn_hist       = meter.create_histogram("nfc.transaction_value_usd", description="NFC transaction value", unit="USD")
anr_counter        = meter.create_counter("anr.count", description="ANR near-miss count")

def android_attrs(activity="MainActivity", fragment="DashboardFragment", battery=None):
    return {
        "android.api_level":              33,
        "android.build.version.release":  "13",
        "android.package_name":           "com.example.securebank",
        "android.activity.name":          activity,
        "android.fragment.name":          fragment,
        "android.battery_level":          round(battery if battery is not None else random.uniform(0.2, 1.0), 2),
        "session.id":                     uuid.uuid4().hex,
    }

results = []
print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

# ── Scenario 1: Cold start with Jetpack Compose ───────────────────────────────
try:
    with tracer.start_as_current_span("app.cold_start", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(android_attrs("SplashActivity", ""))
        span.set_attribute("startup.type", "cold")
        # Application.onCreate
        start_ms = time.time()
        time.sleep(random.uniform(0.15, 0.35))
        with tracer.start_as_current_span("compose.recomposition", kind=SpanKind.INTERNAL) as comp:
            comp.set_attributes(android_attrs())
            comp.set_attribute("compose.composable", "DashboardScreen")
            comp.set_attribute("compose.recomposition_count", 1)
            recompose_counter.add(1, attributes={"composable": "DashboardScreen"})
            time.sleep(random.uniform(0.08, 0.18))
        total_ms = (time.time() - start_ms) * 1000
        span.set_attribute("app.cold_start_ms", round(total_ms, 2))
        cold_start_hist.record(total_ms, attributes={"startup.type": "cold"})
    logger.info("App cold start complete", extra={"cold_start_ms": round(total_ms, 2), "startup_type": "cold"})
    results.append(("Cold start + Jetpack Compose inflation", "OK", None))
except Exception as e:
    results.append(("Cold start + Jetpack Compose inflation", "ERROR", str(e)))

# ── Scenario 2: Biometric unlock ─────────────────────────────────────────────
try:
    with tracer.start_as_current_span("biometric.prompt", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(android_attrs("LockScreenActivity", "BiometricFragment"))
        span.set_attribute("biometric.type", "fingerprint")
        span.set_attribute("biometric.prompt_title", "Authenticate to access SecureBank")
        time.sleep(random.uniform(0.4, 0.9))
        span.set_attribute("biometric.result_code", 1)  # BIOMETRIC_SUCCESS
        span.set_attribute("biometric.result", "success")
        with tracer.start_as_current_span("compose.recomposition", kind=SpanKind.INTERNAL) as comp:
            comp.set_attributes(android_attrs())
            comp.set_attribute("compose.composable", "AccountDashboard")
            comp.set_attribute("compose.recomposition_count", 2)
            recompose_counter.add(2, attributes={"composable": "AccountDashboard"})
            time.sleep(random.uniform(0.05, 0.12))
    logger.info("Biometric unlock successful", extra={"method": "fingerprint"})
    results.append(("Biometric unlock: fingerprint → activity result", "OK", None))
except Exception as e:
    results.append(("Biometric unlock", "ERROR", str(e)))

# ── Scenario 3: Account dashboard parallel Retrofit calls ─────────────────────
try:
    with tracer.start_as_current_span("compose.recomposition", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(android_attrs("MainActivity", "DashboardFragment"))
        span.set_attribute("compose.composable", "AccountDashboard")
        for endpoint in ["balance", "recent_transactions", "card_status"]:
            with tracer.start_as_current_span("retrofit.call", kind=SpanKind.CLIENT) as call:
                call.set_attributes(android_attrs())
                call.set_attribute("http.request.method", "GET")
                call.set_attribute("url.full", f"https://api.securebank.io/v2/{endpoint}")
                call.set_attribute("server.address", "api.securebank.io")
                call.set_attribute("service.peer.name", "securebank-api")
                call.set_attribute("retrofit.service", "BankingApiService")
                call.set_attribute("retrofit.method", f"get{endpoint.title().replace('_', '')}")
                dur_ms = random.uniform(80, 450)
                time.sleep(dur_ms / 1000)
                call.set_attribute("http.response.status_code", 200)
        recompose_counter.add(3, attributes={"composable": "AccountDashboard"})
    logger.info("Dashboard parallel Retrofit calls complete", extra={"endpoints": "balance,transactions,card_status"})
    results.append(("Account dashboard: parallel Retrofit calls", "OK", None))
except Exception as e:
    results.append(("Account dashboard: parallel Retrofit calls", "ERROR", str(e)))

# ── Scenario 4: NFC tap-to-pay ────────────────────────────────────────────────
try:
    with tracer.start_as_current_span("nfc.payment", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(android_attrs("PaymentActivity", "NFCPaymentFragment"))
        span.set_attribute("nfc.technology", "HCE")  # Host Card Emulation
        span.set_attribute("nfc.aid", "A0000000031010")  # Visa AID
        txn_amount = round(random.uniform(5.0, 150.0), 2)
        span.set_attribute("payment.amount_usd", txn_amount)
        span.set_attribute("payment.currency", "USD")
        span.set_attribute("nfc.terminal_id", f"TERM-{uuid.uuid4().hex[:6].upper()}")
        time.sleep(random.uniform(0.1, 0.3))  # NFC tap
        with tracer.start_as_current_span("retrofit.call", kind=SpanKind.CLIENT) as auth:
            auth.set_attributes(android_attrs())
            auth.set_attribute("http.request.method", "POST")
            auth.set_attribute("url.full", "https://api.securebank.io/v2/payments/authorize")
            auth.set_attribute("server.address", "api.securebank.io")
            auth.set_attribute("service.peer.name", "securebank-api")
            time.sleep(random.uniform(0.2, 0.5))
            auth.set_attribute("http.response.status_code", 200)
            auth.set_attribute("payment.authorization_code", uuid.uuid4().hex[:6].upper())
        span.set_attribute("nfc.payment_result", "approved")
        nfc_txn_hist.record(txn_amount, attributes={"payment.method": "nfc_tap"})
    logger.info("NFC tap-to-pay complete", extra={"amount_usd": txn_amount, "method": "HCE"})
    results.append(("Payment: NFC tap-to-pay → POS → receipt", "OK", None))
except Exception as e:
    results.append(("Payment: NFC tap-to-pay", "ERROR", str(e)))

# ── Scenario 5: ANR near-miss → offloaded to coroutine ────────────────────────
try:
    with tracer.start_as_current_span("anr.detected", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(android_attrs("MainActivity", "DashboardFragment"))
        span.set_attribute("anr.blocked_thread", "main")
        span.set_attribute("anr.operation", "crypto_key_derivation")
        span.set_attribute("anr.blocked_ms_estimate", round(random.uniform(2500, 3900), 0))
        # Simulate near-miss: operation offloaded before 5s threshold
        time.sleep(random.uniform(0.08, 0.2))
        with tracer.start_as_current_span("retrofit.call", kind=SpanKind.INTERNAL) as coroutine:
            coroutine.set_attributes(android_attrs())
            coroutine.set_attribute("coroutine.dispatcher", "Dispatchers.IO")
            coroutine.set_attribute("crypto.algorithm", "PBKDF2WithHmacSHA256")
            coroutine.set_attribute("crypto.iterations", 100000)
            time.sleep(random.uniform(0.3, 0.7))
        span.set_attribute("anr.resolved", True)
        span.set_attribute("anr.resolution", "offloaded_to_coroutine")
        anr_counter.add(1, attributes={"anr.resolution": "offloaded_to_coroutine"})
    logger.warning("ANR near-miss detected and resolved", extra={"operation": "crypto_key_derivation", "resolution": "coroutine"})
    results.append(("ANR near-miss: main thread blocked → offloaded to coroutine", "WARN", "Resolved before 5s threshold"))
except Exception as e:
    results.append(("ANR near-miss", "ERROR", str(e)))

# ── Scenario 6: NullPointerException crash ────────────────────────────────────
try:
    with tracer.start_as_current_span("compose.recomposition", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(android_attrs("TransactionActivity", "TransactionListFragment"))
        span.set_attribute("compose.composable", "TransactionListItem")
        try:
            time.sleep(random.uniform(0.02, 0.06))
            err = RuntimeError("NullPointerException: Attempt to invoke virtual method on a null object reference in TransactionAdapter.onBindViewHolder")
            span.record_exception(err, attributes={"exception.escaped": False})
            span.set_status(StatusCode.ERROR, str(err))
            span.set_attribute("error.type", type(err).__name__)
            span.set_attribute("crash.type", "NullPointerException")
            span.set_attribute("crash.reporter", "firebase_crashlytics_bridge")
            logger.error(
                "NPE crash in adapter — caught by Crashlytics bridge",
                extra={"crash.type": "NullPointerException", "composable": "TransactionListItem"},
            )
            results.append(("Crash: NullPointerException in adapter → Crashlytics bridge", "WARN", "Caught by crash reporter"))
        except Exception:
            pass
except Exception as e:
    results.append(("Crash: NullPointerException", "ERROR", str(e)))

o11y.flush()

print()
for scenario, status, note in results:
    symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
    note_str = f"  ({note})" if note else ""
    print(f"  {symbol} {scenario}{note_str}")

ok   = sum(1 for _, s, _ in results if s == "OK")
warn = sum(1 for _, s, _ in results if s == "WARN")
err  = sum(1 for _, s, _ in results if s == "ERROR")
print(f"\n[{SVC}] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → {SVC}")
print("  Metrics: app.cold_start_ms | compose.recomposition_count | nfc.transaction_value_usd | anr.count")
