#!/usr/bin/env python3
"""
Smoke test: Mobile — .NET MAUI (Enterprise Portal)

Simulates iOS and Android variants of a .NET MAUI enterprise app
with Azure AD SSO, offline sync, and Azure Cognitive Services.
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 69-mobile-xamarin-maui/smoke.py
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
    "app.name":              "Enterprise Portal",
    "app.version":           "1.4.0",
    "telemetry.sdk.name":    "opentelemetry-dotnet",
    "telemetry.sdk.version": "1.7.0",
    "telemetry.sdk.language": "dotnet",
}

# ── Bootstrap: iOS ────────────────────────────────────────────────────────────
o11y_ios = O11yBootstrap(
    "mobile-maui-enterpriseapp-ios", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        **COMMON_ATTRS,
        "device.manufacturer":     "Apple",
        "device.model.name":       "iPhone 13",
        "os.name":                 "iOS",
        "os.version":              "16.0",
        "os.type":                 "darwin",
        "os.description":          "iOS 16.0 (20A362)",
    },
)

# ── Bootstrap: Android ────────────────────────────────────────────────────────
o11y_android = O11yBootstrap(
    "mobile-maui-enterpriseapp-android", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        **COMMON_ATTRS,
        "device.manufacturer":     "Xiaomi",
        "device.model.name":       "Redmi Note 12",
        "os.name":                 "Android",
        "os.version":              "12.0",
        "os.type":                 "linux",
        "os.description":          "Android 12 (API 32)",
    },
)

def make_instruments(o11y):
    return {
        "token_refresh":    o11y.meter.create_counter("msal.token_refresh", description="MSAL token refresh count"),
        "delta_records":    o11y.meter.create_histogram("sync.delta_records", description="Offline sync delta records"),
        "azure_api_dur":    o11y.meter.create_histogram("azure.api_duration_ms", description="Azure API call duration", unit="ms"),
    }

def run_scenarios(o11y, platform, instruments):
    tracer = o11y.tracer
    logger = o11y.logger
    results = []

    def maui_attrs(shell_item="Dashboard"):
        return {
            "dotnet.runtime":        ".NET 8.0",
            "maui.shell_item":       shell_item,
            "session.id":            uuid.uuid4().hex,
        }

    # ── Scenario 1: MSAL Azure AD SSO ─────────────────────────────────────────
    try:
        with tracer.start_as_current_span("msal.acquire_token", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(maui_attrs("Login"))
            span.set_attribute("msal.authority", "https://login.microsoftonline.com/contoso.onmicrosoft.com")
            span.set_attribute("msal.client_id", f"app-{uuid.uuid4().hex[:8]}")
            span.set_attribute("msal.scopes", "User.Read,Files.ReadWrite,Sites.ReadWrite.All")
            span.set_attribute("msal.grant_type", "authorization_code")
            time.sleep(random.uniform(0.5, 1.2))
            span.set_attribute("msal.token_type", "Bearer")
            span.set_attribute("msal.token_cached", False)
            span.set_attribute("msal.expires_in_s", 3600)
            instruments["token_refresh"].add(1, attributes={"grant_type": "authorization_code", "platform": platform})
        logger.info("MSAL Azure AD SSO complete", extra={"grant_type": "authorization_code", "platform": platform})
        results.append(("MSAL authentication: Azure AD SSO → token acquisition", "OK", None))
    except Exception as e:
        results.append(("MSAL authentication", "ERROR", str(e)))

    # ── Scenario 2: MAUI Shell navigation ─────────────────────────────────────
    try:
        tabs = ["Dashboard", "Reports", "Approvals"]
        for tab in tabs:
            with tracer.start_as_current_span("maui.navigation", kind=SpanKind.INTERNAL) as span:
                span.set_attributes(maui_attrs(tab))
                span.set_attribute("navigation.type", "shell_tab")
                span.set_attribute("navigation.destination", tab)
                span.set_attribute("navigation.source", tabs[tabs.index(tab) - 1] if tabs.index(tab) > 0 else "Login")
                time.sleep(random.uniform(0.04, 0.12))
        # Flyout menu navigation
        with tracer.start_as_current_span("maui.navigation", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(maui_attrs("Settings"))
            span.set_attribute("navigation.type", "flyout_menu")
            span.set_attribute("navigation.destination", "Settings")
            time.sleep(random.uniform(0.03, 0.08))
        logger.info("MAUI Shell navigation complete", extra={"tabs_visited": tabs, "platform": platform})
        results.append(("MAUI Shell navigation: tabs + flyout menu", "OK", None))
    except Exception as e:
        results.append(("MAUI Shell navigation", "ERROR", str(e)))

    # ── Scenario 3: Offline sync to SharePoint ────────────────────────────────
    try:
        with tracer.start_as_current_span("sync.offline_delta", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(maui_attrs("Reports"))
            pending = random.randint(5, 80)
            span.set_attribute("sync.records_pending", pending)
            span.set_attribute("azure.service", "sharepoint")
            # Read from SQLite local DB
            with tracer.start_as_current_span("sync.sqlite_read", kind=SpanKind.INTERNAL) as db:
                db.set_attributes(maui_attrs())
                db.set_attribute("db.system", "sqlite")
                db.set_attribute("db.operation", "SELECT")
                db.set_attribute("db.table", "offline_queue")
                time.sleep(random.uniform(0.05, 0.15))
            # Push delta to SharePoint REST API
            with tracer.start_as_current_span("sync.offline_delta", kind=SpanKind.CLIENT) as push:
                push.set_attributes(maui_attrs())
                push.set_attribute("http.request.method", "PATCH")
                push.set_attribute("url.full", "https://contoso.sharepoint.com/_api/web/lists/getbytitle('Reports')/items")
                push.set_attribute("server.address", "contoso.sharepoint.com")
                push.set_attribute("service.peer.name", "sharepoint-api")
                push.set_attribute("azure.service", "sharepoint")
                dur_ms = random.uniform(300, 1200)
                time.sleep(dur_ms / 1000)
                push.set_attribute("http.response.status_code", 204)
                push.set_attribute("sync.records_pending", pending)
                instruments["azure_api_dur"].record(dur_ms, attributes={"azure.service": "sharepoint", "platform": platform})
            synced = pending
            span.set_attribute("sync.records_synced", synced)
            instruments["delta_records"].record(synced, attributes={"platform": platform})
        logger.info("Offline delta sync complete", extra={"records_synced": synced, "platform": platform})
        results.append(("Offline sync: SQLite → SharePoint REST API", "OK", None))
    except Exception as e:
        results.append(("Offline sync: SQLite → SharePoint", "ERROR", str(e)))

    # ── Scenario 4: Camera → Azure Computer Vision ────────────────────────────
    try:
        with tracer.start_as_current_span("azure.cognitive", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(maui_attrs("Expenses"))
            span.set_attribute("azure.service", "cognitive-vision")
            span.set_attribute("cognitive.operation", "classify_expense_receipt")
            # Camera capture
            with tracer.start_as_current_span("camera.capture", kind=SpanKind.INTERNAL) as cam:
                cam.set_attributes(maui_attrs())
                cam.set_attribute("camera.resolution", "4032x3024")
                cam.set_attribute("camera.format", "JPEG")
                time.sleep(random.uniform(0.1, 0.3))
            # Azure Computer Vision API
            with tracer.start_as_current_span("azure.cognitive", kind=SpanKind.CLIENT) as cv:
                cv.set_attributes(maui_attrs())
                cv.set_attribute("http.request.method", "POST")
                cv.set_attribute("url.full", "https://contoso.cognitiveservices.azure.com/vision/v3.2/analyze")
                cv.set_attribute("server.address", "contoso.cognitiveservices.azure.com")
                cv.set_attribute("service.peer.name", "azure-cognitive-vision")
                cv.set_attribute("azure.service", "cognitive-vision")
                dur_ms = random.uniform(400, 1500)
                time.sleep(dur_ms / 1000)
                cv.set_attribute("http.response.status_code", 200)
                instruments["azure_api_dur"].record(dur_ms, attributes={"azure.service": "cognitive-vision", "platform": platform})
            span.set_attribute("cognitive.receipt_total_usd", round(random.uniform(5, 500), 2))
            span.set_attribute("cognitive.confidence", round(random.uniform(0.82, 0.99), 3))
        logger.info("Receipt classified via Azure Computer Vision", extra={"platform": platform})
        results.append(("Camera → Azure Computer Vision → classify receipt", "OK", None))
    except Exception as e:
        results.append(("Camera → Azure Computer Vision", "ERROR", str(e)))

    # ── Scenario 5: Push notification via Azure Notification Hubs ─────────────
    try:
        with tracer.start_as_current_span("push.notification", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(maui_attrs("Dashboard"))
            notification_id = uuid.uuid4().hex[:8]
            push_backend = "APNs" if platform == "ios" else "FCM"
            span.set_attribute("push.notification_id", notification_id)
            span.set_attribute("azure.service", "notification-hubs")
            span.set_attribute("push.backend", push_backend)
            span.set_attribute("push.title", "Expense report pending approval")
            span.set_attribute("push.payload_size_bytes", random.randint(256, 4096))
            time.sleep(random.uniform(0.1, 0.3))
            span.set_attribute("push.delivery_status", "delivered")
            instruments["azure_api_dur"].record(random.uniform(50, 200), attributes={"azure.service": "notification-hubs", "platform": platform})
        logger.info("Push notification delivered via ANH", extra={"notification_id": notification_id, "backend": push_backend, "platform": platform})
        results.append(("Push notification: Azure Notification Hubs → FCM/APNs", "OK", None))
    except Exception as e:
        results.append(("Push notification: Azure Notification Hubs", "ERROR", str(e)))

    # ── Scenario 6: Certificate pinning failure (MITM detected) ───────────────
    try:
        with tracer.start_as_current_span("tls.cert_pin_check", kind=SpanKind.CLIENT) as span:
            span.set_attributes(maui_attrs("Login"))
            span.set_attribute("url.full", "https://api.enterprise-portal.io/v1/auth/token")
            span.set_attribute("server.address", "api.enterprise-portal.io")
            span.set_attribute("service.peer.name", "enterprise-portal-api")
            span.set_attribute("tls.cert_pin_algorithm", "sha256")
            span.set_attribute("tls.expected_pin", "sha256/BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=")
            time.sleep(random.uniform(0.05, 0.15))
            err = SecurityError("Certificate pinning validation failed: presented certificate does not match pinned certificate — possible MITM attack")
            span.record_exception(err, attributes={"exception.escaped": False})
            span.set_status(StatusCode.ERROR, str(err))
            span.set_attribute("error.type", type(err).__name__)
            span.set_attribute("tls.pin_failure", True)
            span.set_attribute("security.alert_type", "mitm_suspected")
            logger.error(
                "Certificate pinning failure — MITM suspected, connection blocked",
                extra={"url": "https://api.enterprise-portal.io/v1/auth/token", "platform": platform},
            )
        results.append(("Certificate pinning failure: MITM detected → security alert", "WARN", "Connection blocked"))
    except Exception as e:
        results.append(("Certificate pinning failure", "ERROR", str(e)))

    return results

# ── Inject SecurityError class ─────────────────────────────────────────────────
class SecurityError(Exception):
    pass

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"\n[mobile-maui-enterpriseapp] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")
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
print(f"\n[mobile-maui-enterpriseapp] Done. {ok} OK | {warn} WARN | {err} ERROR")
print("  Kibana → APM → mobile-maui-enterpriseapp-ios / -android")
print("  Metrics: msal.token_refresh | sync.delta_records | azure.api_duration_ms")
