#!/usr/bin/env python3
"""
Smoke test: Mobile — Flutter (FinanceApp)

Simulates iOS and Android variants of a Flutter finance app.
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 66-mobile-flutter/smoke.py
"""

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

COMMON_ATTRS = {
    "app.name":              "FinanceApp",
    "app.version":           "2.1.0",
    "telemetry.sdk.name":    "opentelemetry_dart",
    "telemetry.sdk.version": "0.3.0",
    "telemetry.sdk.language": "dart",
}

# ── Bootstrap: iOS ────────────────────────────────────────────────────────────
o11y_ios = O11yBootstrap(
    "mobile-flutter-financeapp-ios", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        **COMMON_ATTRS,
        "device.manufacturer":     "Apple",
        "device.model.name":       "iPhone 14",
        "os.name":                 "iOS",
        "os.version":              "16.7.2",
        "os.type":                 "darwin",
        "os.description":          "iOS 16.7.2 (20H115)",
    },
)

# ── Bootstrap: Android ───────────────────────────────────────────────────────
o11y_android = O11yBootstrap(
    "mobile-flutter-financeapp-android", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        **COMMON_ATTRS,
        "device.manufacturer":     "Samsung",
        "device.model.name":       "Galaxy S23",
        "os.name":                 "Android",
        "os.version":              "13.0",
        "os.type":                 "linux",
        "os.description":          "Android 13 (API 33)",
    },
)

def make_instruments(o11y):
    return {
        "frames_dropped":   o11y.meter.create_counter("flutter.frames_dropped", description="Dropped frame count"),
        "frame_build_ms":   o11y.meter.create_histogram("flutter.frame_build_ms", description="Frame build duration", unit="ms"),
        "http_duration_ms": o11y.meter.create_histogram("http.client.duration_ms", description="HTTP client request duration", unit="ms"),
        "auth_attempts":    o11y.meter.create_counter("biometric.auth.attempts", description="Biometric auth attempts"),
    }

def run_scenarios(o11y, platform, instruments):
    tracer = o11y.tracer
    logger = o11y.logger
    results = []
    engine = "impeller" if platform == "ios" else "skia"
    dart_version = "3.2.0"
    session_id = uuid.uuid4().hex

    def flutter_attrs(widget):
        return {
            "flutter.widget":       widget,
            "flutter.dart_version": dart_version,
            "flutter.engine":       engine,
            "session.id":           session_id,
        }

    # ── Scenario 1: Widget tree build (cold start) ────────────────────────────
    try:
        with tracer.start_as_current_span("flutter.widget.build", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(flutter_attrs("MaterialApp"))
            span.set_attribute("startup.type", "cold")
            build_ms = random.uniform(120, 280)
            span.set_attribute("flutter.frame_build_ms", round(build_ms, 2))
            time.sleep(build_ms / 1000)
            with tracer.start_as_current_span("flutter.frame", kind=SpanKind.INTERNAL) as frame:
                frame.set_attributes(flutter_attrs("DashboardScreen"))
                frame_ms = random.uniform(8, 20)
                frame.set_attribute("flutter.frame_build_ms", round(frame_ms, 2))
                time.sleep(frame_ms / 1000)
                instruments["frame_build_ms"].record(frame_ms, attributes={"widget": "DashboardScreen", "platform": platform})
                if frame_ms > 16:
                    instruments["frames_dropped"].add(1, attributes={"platform": platform})
        logger.info("Widget tree build complete", extra={"build_ms": round(build_ms, 2), "platform": platform})
        results.append(("Widget tree build (cold start)", "OK", None))
    except Exception as e:
        results.append(("Widget tree build (cold start)", "ERROR", str(e)))

    # ── Scenario 2: Dashboard parallel API calls ──────────────────────────────
    try:
        with tracer.start_as_current_span("flutter.widget.build", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(flutter_attrs("DashboardScreen"))
            span.set_attribute("screen.name", "Dashboard")
            for api in ["balance", "transactions", "portfolio"]:
                with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as call:
                    call.set_attributes(flutter_attrs(f"{api.capitalize()}Widget"))
                    call.set_attribute("http.request.method", "GET")
                    call.set_attribute("url.full", f"https://api.financeapp.io/v1/{api}")
                    call.set_attribute("server.address", "api.financeapp.io")
                    call.set_attribute("service.peer.name", "finance-api")
                    dur_ms = random.uniform(80, 400)
                    time.sleep(dur_ms / 1000)
                    call.set_attribute("http.response.status_code", 200)
                    instruments["http_duration_ms"].record(dur_ms, attributes={"api": api, "platform": platform})
        logger.info("Dashboard parallel API calls complete", extra={"apis": "balance,transactions,portfolio", "platform": platform})
        results.append(("Dashboard: parallel balance + transactions + portfolio", "OK", None))
    except Exception as e:
        results.append(("Dashboard: parallel balance + transactions + portfolio", "ERROR", str(e)))

    # ── Scenario 3: BiometricAuth FaceID ─────────────────────────────────────
    try:
        with tracer.start_as_current_span("biometric.auth", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(flutter_attrs("BiometricAuthWidget"))
            span.set_attribute("biometric.type", "face_id" if platform == "ios" else "fingerprint")
            # First attempt fails
            instruments["auth_attempts"].add(1, attributes={"platform": platform, "result": "failure"})
            time.sleep(random.uniform(0.3, 0.6))
            logger.warning("Biometric auth failed, retrying", extra={"attempt": 1, "platform": platform})
            # Second attempt succeeds
            instruments["auth_attempts"].add(1, attributes={"platform": platform, "result": "success"})
            time.sleep(random.uniform(0.2, 0.5))
            span.set_attribute("biometric.attempts", 2)
            span.set_attribute("biometric.result", "success")
        logger.info("BiometricAuth success after retry", extra={"total_attempts": 2, "platform": platform})
        results.append(("BiometricAuth: FaceID fail then success", "OK", None))
    except Exception as e:
        results.append(("BiometricAuth: FaceID fail then success", "ERROR", str(e)))

    # ── Scenario 4: Transfer flow ─────────────────────────────────────────────
    try:
        transfer_id = uuid.uuid4().hex[:8]
        for step in ["sender", "amount", "recipient", "confirm"]:
            with tracer.start_as_current_span("transfer.initiate", kind=SpanKind.INTERNAL) as span:
                span.set_attributes(flutter_attrs(f"Transfer{step.capitalize()}Screen"))
                span.set_attribute("transfer.step", step)
                span.set_attribute("transfer.id", transfer_id)
                time.sleep(random.uniform(0.04, 0.12))
        with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as span:
            span.set_attributes(flutter_attrs("TransferConfirmScreen"))
            span.set_attribute("http.request.method", "POST")
            span.set_attribute("url.full", "https://api.financeapp.io/v1/transfers")
            span.set_attribute("server.address", "api.financeapp.io")
            span.set_attribute("service.peer.name", "finance-api")
            span.set_attribute("transfer.amount_usd", round(random.uniform(10, 5000), 2))
            dur_ms = random.uniform(200, 700)
            time.sleep(dur_ms / 1000)
            span.set_attribute("http.response.status_code", 201)
            instruments["http_duration_ms"].record(dur_ms, attributes={"api": "transfer", "platform": platform})
        logger.info("Transfer flow complete", extra={"transfer_id": transfer_id, "platform": platform})
        results.append(("Transfer flow: sender → amount → recipient → confirm → success", "OK", None))
    except Exception as e:
        results.append(("Transfer flow", "ERROR", str(e)))

    # ── Scenario 5: Background sync ───────────────────────────────────────────
    try:
        with tracer.start_as_current_span("background.sync", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(flutter_attrs("PortfolioSyncService"))
            span.set_attribute("app.in_foreground", False)
            span.set_attribute("sync.type", "portfolio")
            dur_ms = random.uniform(500, 1500)
            time.sleep(dur_ms / 1000)
            span.set_attribute("sync.records_updated", random.randint(5, 50))
            instruments["http_duration_ms"].record(dur_ms, attributes={"api": "portfolio_sync", "platform": platform})
        logger.info("Background portfolio sync complete", extra={"platform": platform})
        results.append(("Background sync: portfolio refresh while backgrounded", "OK", None))
    except Exception as e:
        results.append(("Background sync", "ERROR", str(e)))

    # ── Scenario 6: 503 error with retry + cache fallback ─────────────────────
    try:
        with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as span:
            span.set_attributes(flutter_attrs("TransactionListWidget"))
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("url.full", "https://api.financeapp.io/v1/transactions")
            span.set_attribute("server.address", "api.financeapp.io")
            span.set_attribute("service.peer.name", "finance-api")
            for attempt in range(1, 4):
                dur_ms = random.uniform(100, 300)
                time.sleep(dur_ms / 1000)
                instruments["http_duration_ms"].record(dur_ms, attributes={"api": "transactions", "platform": platform})
                if attempt < 3:
                    logger.warning("Transactions API 503, retrying", extra={"attempt": attempt, "platform": platform})
                else:
                    err = ConnectionError("transactions API returned 503 after 3 retries")
                    span.record_exception(err, attributes={"exception.escaped": False})
                    span.set_status(StatusCode.ERROR, str(err))
                    span.set_attribute("error.type", type(err).__name__)
                    span.set_attribute("http.response.status_code", 503)
                    span.set_attribute("fallback.used", "local_cache")
            logger.warning("Transactions fallback to cache", extra={"platform": platform})
        results.append(("Network error: 503 → retry → cache fallback", "WARN", "Served from cache"))
    except Exception as e:
        results.append(("Network error: 503 → retry → cache fallback", "ERROR", str(e)))

    return results

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"\n[mobile-flutter-financeapp] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Platform: iOS + Android variants\n")

all_results = []
for platform, o11y in [("ios", o11y_ios), ("android", o11y_android)]:
    print(f"  -- {platform.upper()} --")
    instruments = make_instruments(o11y)
    res = run_scenarios(o11y, platform, instruments)
    for scenario, status, note in res:
        symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
        note_str = f"  ({note})" if note else ""
        print(f"    {symbol} [{platform}] {scenario}{note_str}")
    all_results.extend(res)

o11y_ios.flush()
o11y_android.flush()

ok   = sum(1 for _, s, _ in all_results if s == "OK")
warn = sum(1 for _, s, _ in all_results if s == "WARN")
err  = sum(1 for _, s, _ in all_results if s == "ERROR")
print(f"\n[mobile-flutter-financeapp] Done. {ok} OK | {warn} WARN | {err} ERROR")
print("  Kibana → APM → mobile-flutter-financeapp-ios / -android")
print("  Metrics: flutter.frames_dropped | flutter.frame_build_ms | http.client.duration_ms | biometric.auth.attempts")
