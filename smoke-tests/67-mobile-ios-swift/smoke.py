#!/usr/bin/env python3
"""
Smoke test: Mobile — iOS Swift (HealthKit Tracker)

Simulates an iPad Pro health tracking app built with Swift/SwiftUI.
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 67-mobile-ios-swift/smoke.py
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
SVC      = "mobile-ios-healthapp"

o11y = O11yBootstrap(
    SVC, ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        "os.name":                 "iOS",
        "os.version":              "17.3.0",
        "os.type":                 "darwin",
        "os.description":          "iOS 17.3.0 (21D50)",
        "device.manufacturer":     "Apple",
        "device.model.name":       'iPad Pro 12.9"',
        "device.model.identifier": "iPad14,5",
        "app.name":                "HealthKit Tracker",
        "app.version":             "3.0.2",
        "telemetry.sdk.name":      "opentelemetry-swift",
        "telemetry.sdk.version":   "1.9.0",
        "telemetry.sdk.language":  "swift",
    },
)

tracer = o11y.tracer
logger = o11y.logger
meter  = o11y.meter

# ── Metrics ───────────────────────────────────────────────────────────────────
sync_records_counter   = meter.create_counter("healthkit.sync_records", description="HealthKit records synced")
workout_duration_hist  = meter.create_histogram("workout.duration_s", description="Workout session duration", unit="s")
purchase_value_hist    = meter.create_histogram("storekit.purchase_value_usd", description="In-app purchase value", unit="USD")

def ios_attrs(thermal="nominal", low_power=False):
    return {
        "ios.bundle_id":          "com.example.healthtracker",
        "ios.sdk_version":        "17.3",
        "ios.deployment_target":  "15.0",
        "ios.thermal_state":      thermal,
        "ios.low_power_mode":     low_power,
        "session.id":             uuid.uuid4().hex,
    }

results = []
print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

# ── Scenario 1: HealthKit authorization → initial data sync ──────────────────
try:
    with tracer.start_as_current_span("healthkit.authorize", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(ios_attrs())
        span.set_attribute("healthkit.data_types", "heart_rate,steps,sleep,workout")
        time.sleep(random.uniform(0.3, 0.8))
        span.set_attribute("healthkit.authorization_result", "granted")
        with tracer.start_as_current_span("healthkit.initial_sync", kind=SpanKind.INTERNAL) as sync_span:
            sync_span.set_attributes(ios_attrs())
            records = random.randint(200, 1500)
            sync_span.set_attribute("healthkit.records_synced", records)
            time.sleep(random.uniform(0.5, 1.2))
            sync_records_counter.add(records, attributes={"data_type": "mixed", "sync_type": "initial"})
    logger.info("HealthKit authorized and synced", extra={"records_synced": records})
    results.append(("HealthKit authorization → initial sync", "OK", None))
except Exception as e:
    results.append(("HealthKit authorization → initial sync", "ERROR", str(e)))

# ── Scenario 2: Workout session with GPS + heart rate ────────────────────────
try:
    workout_id = uuid.uuid4().hex[:8]
    with tracer.start_as_current_span("workout.session", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(ios_attrs(thermal="fair"))
        span.set_attribute("workout.type", "running")
        span.set_attribute("workout.id", workout_id)
        span.set_attribute("workout.gps_enabled", True)
        start_t = time.time()
        # GPS tracking
        with tracer.start_as_current_span("workout.gps_tracking", kind=SpanKind.INTERNAL) as gps:
            gps.set_attributes(ios_attrs())
            gps.set_attribute("location.accuracy_m", round(random.uniform(2, 8), 1))
            gps.set_attribute("location.samples", random.randint(80, 200))
            time.sleep(random.uniform(0.2, 0.5))
        # Heart rate sampling
        with tracer.start_as_current_span("workout.heart_rate_sampling", kind=SpanKind.INTERNAL) as hr:
            hr.set_attributes(ios_attrs())
            hr.set_attribute("heart_rate.avg_bpm", random.randint(130, 165))
            hr.set_attribute("heart_rate.max_bpm", random.randint(170, 195))
            hr.set_attribute("heart_rate.samples", random.randint(40, 120))
            time.sleep(random.uniform(0.1, 0.3))
        duration_s = time.time() - start_t
        span.set_attribute("workout.duration_s", round(duration_s, 2))
        span.set_attribute("workout.distance_m", round(random.uniform(1000, 8000), 1))
        workout_duration_hist.record(duration_s, attributes={"workout.type": "running"})
    logger.info("Workout session complete", extra={"workout_id": workout_id, "duration_s": round(duration_s, 2)})
    results.append(("Workout session: start → GPS → heart rate → end", "OK", None))
except Exception as e:
    results.append(("Workout session", "ERROR", str(e)))

# ── Scenario 3: Background app refresh ────────────────────────────────────────
try:
    with tracer.start_as_current_span("background.refresh", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(ios_attrs(low_power=False))
        span.set_attribute("app.in_foreground", False)
        span.set_attribute("background.task", "health_data_fetch")
        with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as req:
            req.set_attributes(ios_attrs())
            req.set_attribute("http.request.method", "GET")
            req.set_attribute("url.full", "https://api.healthtracker.io/v1/health-data")
            req.set_attribute("server.address", "api.healthtracker.io")
            req.set_attribute("service.peer.name", "healthkit-api")
            dur_ms = random.uniform(200, 600)
            time.sleep(dur_ms / 1000)
            req.set_attribute("http.response.status_code", 200)
            req.set_attribute("http.response_size_bytes", random.randint(4096, 65536))
        records = random.randint(10, 80)
        span.set_attribute("background.records_fetched", records)
        sync_records_counter.add(records, attributes={"data_type": "server_health", "sync_type": "background"})
    logger.info("Background app refresh complete", extra={"records_fetched": records})
    results.append(("Background app refresh: fetch health data while suspended", "OK", None))
except Exception as e:
    results.append(("Background app refresh", "ERROR", str(e)))

# ── Scenario 4: WatchKit → companion app communication ────────────────────────
try:
    with tracer.start_as_current_span("watchkit.message", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(ios_attrs())
        span.set_attribute("watchkit.message_type", "health_update")
        span.set_attribute("watchkit.watch_model", "Apple Watch Series 9")
        span.set_attribute("watchkit.watch_os_version", "10.2")
        payload = {"heart_rate": random.randint(60, 100), "steps": random.randint(500, 8000)}
        span.set_attribute("watchkit.payload_size_bytes", len(str(payload)))
        time.sleep(random.uniform(0.05, 0.15))
        span.set_attribute("watchkit.transfer_result", "success")
        sync_records_counter.add(1, attributes={"data_type": "watch_sync", "sync_type": "realtime"})
    logger.info("WatchKit message sent to companion", extra={"message_type": "health_update", "payload": str(payload)})
    results.append(("WatchKit extension → companion app communication", "OK", None))
except Exception as e:
    results.append(("WatchKit communication", "ERROR", str(e)))

# ── Scenario 5: StoreKit in-app purchase ──────────────────────────────────────
try:
    with tracer.start_as_current_span("storekit.purchase", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(ios_attrs())
        product_id = "com.example.healthtracker.premium.annual"
        price_usd = 49.99
        span.set_attribute("storekit.product_id", product_id)
        span.set_attribute("storekit.price_usd", price_usd)
        span.set_attribute("storekit.currency", "USD")
        time.sleep(random.uniform(0.5, 1.0))  # StoreKit UI
        # Receipt validation
        with tracer.start_as_current_span("storekit.receipt_validation", kind=SpanKind.CLIENT) as val:
            val.set_attributes(ios_attrs())
            val.set_attribute("http.request.method", "POST")
            val.set_attribute("url.full", "https://buy.itunes.apple.com/verifyReceipt")
            val.set_attribute("server.address", "buy.itunes.apple.com")
            val.set_attribute("service.peer.name", "apple-storekit-api")
            time.sleep(random.uniform(0.3, 0.8))
            val.set_attribute("http.response.status_code", 200)
            val.set_attribute("storekit.receipt_valid", True)
        span.set_attribute("storekit.transaction_id", uuid.uuid4().hex[:12].upper())
        span.set_attribute("storekit.purchase_result", "purchased")
        purchase_value_hist.record(price_usd, attributes={"product_type": "subscription"})
    logger.info("StoreKit purchase complete", extra={"product_id": product_id, "price_usd": price_usd})
    results.append(("In-app purchase: StoreKit subscription → receipt validation", "OK", None))
except Exception as e:
    results.append(("In-app purchase: StoreKit", "ERROR", str(e)))

# ── Scenario 6: Silent push → background fetch → local notification ───────────
try:
    with tracer.start_as_current_span("push.background_fetch", kind=SpanKind.INTERNAL) as span:
        span.set_attributes(ios_attrs(low_power=True))
        notification_id = uuid.uuid4().hex[:8]
        span.set_attribute("push.notification_id", notification_id)
        span.set_attribute("push.type", "silent")
        span.set_attribute("push.apns_priority", 5)
        span.set_attribute("app.in_foreground", False)
        # Background data fetch
        with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as req:
            req.set_attributes(ios_attrs())
            req.set_attribute("http.request.method", "GET")
            req.set_attribute("url.full", "https://api.healthtracker.io/v1/alerts")
            req.set_attribute("server.address", "api.healthtracker.io")
            req.set_attribute("service.peer.name", "healthkit-api")
            time.sleep(random.uniform(0.15, 0.4))
            req.set_attribute("http.response.status_code", 200)
        # Local notification dispatch
        with tracer.start_as_current_span("push.local_notification", kind=SpanKind.INTERNAL) as local:
            local.set_attributes(ios_attrs())
            local.set_attribute("notification.title", "Daily step goal reached!")
            local.set_attribute("notification.body", "You've hit 10,000 steps today.")
            time.sleep(random.uniform(0.01, 0.03))
        span.set_attribute("push.background_fetch_result", "new_data")
    logger.info("Silent push handled, local notification scheduled", extra={"notification_id": notification_id})
    results.append(("Silent push → background fetch → local notification", "OK", None))
except Exception as e:
    results.append(("Silent push → background fetch", "ERROR", str(e)))

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
print("  Metrics: healthkit.sync_records | workout.duration_s | storekit.purchase_value_usd")
