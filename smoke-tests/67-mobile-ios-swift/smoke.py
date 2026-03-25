#!/usr/bin/env python3
"""
Smoke test: Mobile — iOS Swift (HealthKit Tracker)

Simulates an iPad Pro health tracking app built with Swift/SwiftUI using the
EDOT iOS SDK (elastic/apm-agent-ios — ElasticApmAgent.start(with:)).
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 67-mobile-ios-swift/smoke.py
"""

import os, sys, time, random, uuid
import uuid as _uuid
from pathlib import Path

# EDOT iOS automatically generates and attaches session.id to all signals.
# Sessions expire after 30 min of inactivity, max 4 hours.
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
SVC      = "mobile-ios-healthapp"

ios = O11yBootstrap(
    SVC, ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        # EDOT iOS — ElasticApmAgent.start(with: AgentConfigBuilder()
        #   .withExportUrl(url).withApiKey(key).build())
        "telemetry.sdk.name":     "opentelemetry-swift",  # base SDK (EDOT wraps this)
        "telemetry.sdk.version":  "1.17.0",
        "telemetry.sdk.language": "swift",
        "telemetry.distro.name":  "elastic",              # EDOT-specific
        "telemetry.distro.version": "2.0.0",              # EDOT iOS latest
        "os.type":        "darwin",
        "os.name":        "iOS",
        "os.version":     "17.3.0",
        "os.description": "iOS 17.3.0 (21D50)",
        "os.build_id":    "21D50",
        "device.manufacturer":     "Apple",
        "device.model.name":       'iPad Pro 12.9"',
        "device.model.identifier": "iPad14,5",
        "app.name":    "HealthKit Tracker",
        "app.version": "3.0.2",
        # deployment.environment is set via AgentConfigBuilder in EDOT iOS
    },
)

# ── Metrics ───────────────────────────────────────────────────────────────────
sync_records_counter   = ios.meter.create_counter("healthkit.sync_records", description="HealthKit records synced")
workout_duration_hist  = ios.meter.create_histogram("workout.duration_s", description="Workout session duration", unit="s")
purchase_value_hist    = ios.meter.create_histogram("storekit.purchase_value_usd", description="In-app purchase value", unit="USD")

def ios_attrs(thermal="nominal", low_power=False):
    return {
        "ios.bundle_id":          "com.example.healthtracker",
        "ios.sdk_version":        "17.3",
        "ios.deployment_target":  "15.0",
        "ios.thermal_state":      thermal,
        "ios.low_power_mode":     low_power,
    }

results = []

print(f"\n{'='*60}")
print("EDOT-Autopilot | 67-mobile-ios-swift | EDOT iOS SDK v2.0.0")
print("Simulates elastic/apm-agent-ios — ElasticApmAgent.start(with:)")
print(f"{'='*60}")

# ── Scenario 1: EDOT agent start — lifecycle events + resource detection ──────
def scen_edot_agent_start():
    """EDOT iOS: ElasticApmAgent initialises — lifecycle events + resource detection auto-run."""
    with ios.tracer.start_as_current_span("ElasticApmAgent.start", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id",                   EDOT_SESSION_ID)
        span.set_attribute("edot.agent.config.export_url", "https://<deployment>.apm.<region>.cloud.es.io")
        span.set_attribute("edot.agent.config.auth",       "ApiKey")
        span.set_attribute("edot.instrumentation.crash_reporting",           True)
        span.set_attribute("edot.instrumentation.url_session",               True)
        span.set_attribute("edot.instrumentation.view_controller",           True)
        span.set_attribute("edot.instrumentation.app_metric",                True)
        span.set_attribute("edot.instrumentation.system_metrics",            True)
        span.set_attribute("edot.instrumentation.lifecycle_events",          True)
        span.set_attribute("edot.instrumentation.persistence_preset",        "lowRuntimeImpact")
        span.set_attribute("edot.central_config.enabled",                    True)
        span.set_attribute("edot.central_config.url",      "https://<apm-server>/config/v1/agents")
        span.set_attribute("startup.type", "cold")

        # EDOT auto-instruments view controller lifecycle
        with ios.tracer.start_as_current_span("ViewController.viewDidLoad", kind=SpanKind.INTERNAL) as vc:
            vc.set_attribute("session.id",            EDOT_SESSION_ID)
            vc.set_attribute("viewcontroller.name",   "HealthDashboardViewController")
            vc.set_attribute("viewcontroller.event",  "viewDidLoad")

        with ios.tracer.start_as_current_span("ViewController.viewDidAppear", kind=SpanKind.INTERNAL) as vc:
            vc.set_attribute("session.id",           EDOT_SESSION_ID)
            vc.set_attribute("viewcontroller.name",  "HealthDashboardViewController")
            vc.set_attribute("viewcontroller.event", "viewDidAppear")
            vc.set_attribute("viewcontroller.render_ms", 38)

        ios.logger.info("EDOT iOS agent started", extra={
            "session.id": EDOT_SESSION_ID,
            "edot_version": "2.0.0",
            "startup_type": "cold",
        })

try:
    scen_edot_agent_start()
    results.append(("EDOT agent start — lifecycle events + ViewController auto-instrument", "OK", None))
except Exception as e:
    results.append(("EDOT agent start — lifecycle events + ViewController auto-instrument", "ERROR", str(e)))

# ── Scenario 2: HealthKit sync with NSURLSession auto-instrumented span ───────
try:
    with ios.tracer.start_as_current_span("healthkit.authorize", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id", EDOT_SESSION_ID)
        span.set_attributes(ios_attrs())
        span.set_attribute("healthkit.data_types", "heart_rate,steps,sleep,workout")
        time.sleep(random.uniform(0.3, 0.8))
        span.set_attribute("healthkit.authorization_result", "granted")
        with ios.tracer.start_as_current_span("healthkit.initial_sync", kind=SpanKind.INTERNAL) as sync_span:
            sync_span.set_attribute("session.id", EDOT_SESSION_ID)
            sync_span.set_attributes(ios_attrs())
            records = random.randint(200, 1500)
            sync_span.set_attribute("healthkit.records_synced", records)
            time.sleep(random.uniform(0.2, 0.5))

            # EDOT iOS: NSURLSessionInstrumentation auto-creates this span
            with ios.tracer.start_as_current_span("NSURLSession dataTask", kind=SpanKind.CLIENT) as http:
                http.set_attribute("session.id",                EDOT_SESSION_ID)
                http.set_attribute("http.request.method",       "POST")
                http.set_attribute("url.full",                  "https://api.healthkittracker.io/v2/sync")
                http.set_attribute("http.response.status_code", 200)
                http.set_attribute("server.address",            "api.healthkittracker.io")
                http.set_attribute("service.peer.name",         "healthkit-api")
                http.set_attribute("url_session.task_type",     "dataTask")  # EDOT-specific
                http.set_attribute("network.protocol.version",  "2")         # HTTP/2
                time.sleep(random.uniform(0.1, 0.3))

            sync_records_counter.add(records, attributes={"data_type": "mixed", "sync_type": "initial"})
    ios.logger.info("HealthKit authorized and synced", extra={"session.id": EDOT_SESSION_ID, "records_synced": records})
    results.append(("HealthKit authorization → initial sync (NSURLSession auto-span)", "OK", None))
except Exception as e:
    results.append(("HealthKit authorization → initial sync", "ERROR", str(e)))

# ── Scenario 3: Workout session with GPS + heart rate ────────────────────────
try:
    workout_id = uuid.uuid4().hex[:8]
    with ios.tracer.start_as_current_span("workout.session", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id", EDOT_SESSION_ID)
        span.set_attributes(ios_attrs(thermal="fair"))
        span.set_attribute("workout.type", "running")
        span.set_attribute("workout.id", workout_id)
        span.set_attribute("workout.gps_enabled", True)
        start_t = time.time()
        # GPS tracking
        with ios.tracer.start_as_current_span("workout.gps_tracking", kind=SpanKind.INTERNAL) as gps:
            gps.set_attribute("session.id", EDOT_SESSION_ID)
            gps.set_attributes(ios_attrs())
            gps.set_attribute("location.accuracy_m", round(random.uniform(2, 8), 1))
            gps.set_attribute("location.samples", random.randint(80, 200))
            time.sleep(random.uniform(0.2, 0.5))
        # Heart rate sampling
        with ios.tracer.start_as_current_span("workout.heart_rate_sampling", kind=SpanKind.INTERNAL) as hr:
            hr.set_attribute("session.id", EDOT_SESSION_ID)
            hr.set_attributes(ios_attrs())
            hr.set_attribute("heart_rate.avg_bpm", random.randint(130, 165))
            hr.set_attribute("heart_rate.max_bpm", random.randint(170, 195))
            hr.set_attribute("heart_rate.samples", random.randint(40, 120))
            time.sleep(random.uniform(0.1, 0.3))
        duration_s = time.time() - start_t
        span.set_attribute("workout.duration_s", round(duration_s, 2))
        span.set_attribute("workout.distance_m", round(random.uniform(1000, 8000), 1))
        workout_duration_hist.record(duration_s, attributes={"workout.type": "running"})
    ios.logger.info("Workout session complete", extra={"session.id": EDOT_SESSION_ID, "workout_id": workout_id, "duration_s": round(duration_s, 2)})
    results.append(("Workout session: start → GPS → heart rate → end", "OK", None))
except Exception as e:
    results.append(("Workout session", "ERROR", str(e)))

# ── Scenario 4: WatchKit → companion app communication ────────────────────────
try:
    with ios.tracer.start_as_current_span("watchkit.message", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id", EDOT_SESSION_ID)
        span.set_attributes(ios_attrs())
        span.set_attribute("watchkit.message_type", "health_update")
        span.set_attribute("watchkit.watch_model", "Apple Watch Series 9")
        span.set_attribute("watchkit.watch_os_version", "10.2")
        payload = {"heart_rate": random.randint(60, 100), "steps": random.randint(500, 8000)}
        span.set_attribute("watchkit.payload_size_bytes", len(str(payload)))
        time.sleep(random.uniform(0.05, 0.15))
        span.set_attribute("watchkit.transfer_result", "success")
        sync_records_counter.add(1, attributes={"data_type": "watch_sync", "sync_type": "realtime"})
    ios.logger.info("WatchKit message sent to companion", extra={"session.id": EDOT_SESSION_ID, "message_type": "health_update", "payload": str(payload)})
    results.append(("WatchKit extension → companion app communication", "OK", None))
except Exception as e:
    results.append(("WatchKit communication", "ERROR", str(e)))

# ── Scenario 5: StoreKit in-app purchase ──────────────────────────────────────
try:
    with ios.tracer.start_as_current_span("storekit.purchase", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id", EDOT_SESSION_ID)
        span.set_attributes(ios_attrs())
        product_id = "com.example.healthtracker.premium.annual"
        price_usd = 49.99
        span.set_attribute("storekit.product_id", product_id)
        span.set_attribute("storekit.price_usd", price_usd)
        span.set_attribute("storekit.currency", "USD")
        time.sleep(random.uniform(0.5, 1.0))  # StoreKit UI
        # Receipt validation
        with ios.tracer.start_as_current_span("storekit.receipt_validation", kind=SpanKind.CLIENT) as val:
            val.set_attribute("session.id", EDOT_SESSION_ID)
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

    # EDOT auto-collects MetricKit + system metrics
    ios.meter.create_histogram("metrickit.cpu_time_ms",
        description="MetricKit cumulative CPU time — auto-collected by EDOT iOS",
        unit="ms"
    ).record(245, {"app.state": "foreground"})

    ios.meter.create_observable_gauge(
        "system.memory.usage",
        callbacks=[lambda obs: obs.observe(148_000_000, {"memory.type": "used"})],
        description="Device memory usage — auto-collected by EDOT iOS",
        unit="By",
    )

    ios.logger.info("StoreKit purchase complete", extra={"session.id": EDOT_SESSION_ID, "product_id": product_id, "price_usd": price_usd})
    results.append(("In-app purchase: StoreKit subscription → receipt validation + MetricKit", "OK", None))
except Exception as e:
    results.append(("In-app purchase: StoreKit", "ERROR", str(e)))

# ── Scenario 6: Silent push → background fetch → local notification ───────────
try:
    with ios.tracer.start_as_current_span("push.background_fetch", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("session.id", EDOT_SESSION_ID)
        span.set_attributes(ios_attrs(low_power=True))
        notification_id = uuid.uuid4().hex[:8]
        span.set_attribute("push.notification_id", notification_id)
        span.set_attribute("push.type", "silent")
        span.set_attribute("push.apns_priority", 5)
        span.set_attribute("app.in_foreground", False)
        # Background data fetch
        with ios.tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as req:
            req.set_attribute("session.id", EDOT_SESSION_ID)
            req.set_attributes(ios_attrs())
            req.set_attribute("http.request.method", "GET")
            req.set_attribute("url.full", "https://api.healthtracker.io/v1/alerts")
            req.set_attribute("server.address", "api.healthtracker.io")
            req.set_attribute("service.peer.name", "healthkit-api")
            time.sleep(random.uniform(0.15, 0.4))
            req.set_attribute("http.response.status_code", 200)
        # Local notification dispatch
        with ios.tracer.start_as_current_span("push.local_notification", kind=SpanKind.INTERNAL) as local:
            local.set_attribute("session.id", EDOT_SESSION_ID)
            local.set_attributes(ios_attrs())
            local.set_attribute("notification.title", "Daily step goal reached!")
            local.set_attribute("notification.body", "You've hit 10,000 steps today.")
            time.sleep(random.uniform(0.01, 0.03))
        span.set_attribute("push.background_fetch_result", "new_data")
    ios.logger.info("Silent push handled, local notification scheduled", extra={"session.id": EDOT_SESSION_ID, "notification_id": notification_id})
    results.append(("Silent push → background fetch → local notification", "OK", None))
except Exception as e:
    results.append(("Silent push → background fetch", "ERROR", str(e)))

ios.flush()

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
print("  Metrics: healthkit.sync_records | workout.duration_s | storekit.purchase_value_usd | metrickit.cpu_time_ms | system.memory.usage")
