#!/usr/bin/env python3
"""
Smoke test: Mobile — Ionic (TravelBooker)

Simulates iOS, Android, and PWA variants of an Ionic travel booking app.
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 70-mobile-ionic/smoke.py
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
    "app.name":              "TravelBooker",
    "app.version":           "2.8.0",
    "telemetry.sdk.name":    "opentelemetry-js",
    "telemetry.sdk.version": "1.18.0",
    "telemetry.sdk.language": "javascript",
}

# ── Bootstrap: iOS ────────────────────────────────────────────────────────────
o11y_ios = O11yBootstrap(
    "mobile-ionic-travelapp-ios", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        **COMMON_ATTRS,
        "device.manufacturer":     "Apple",
        "device.model.name":       "iPhone 12",
        "os.name":                 "iOS",
        "os.version":              "15.8",
        "os.type":                 "darwin",
        "os.description":          "iOS 15.8 (19H370)",
    },
)

# ── Bootstrap: Android ────────────────────────────────────────────────────────
o11y_android = O11yBootstrap(
    "mobile-ionic-travelapp-android", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        **COMMON_ATTRS,
        "device.manufacturer":     "OnePlus",
        "device.model.name":       "Nord",
        "os.name":                 "Android",
        "os.version":              "12.0",
        "os.type":                 "linux",
        "os.description":          "Android 12 (API 32)",
    },
)

# ── Bootstrap: PWA ────────────────────────────────────────────────────────────
o11y_pwa = O11yBootstrap(
    "mobile-ionic-travelapp-pwa", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs={
        **COMMON_ATTRS,
        "browser.name":     "Chrome",
        "browser.version":  "120.0",
        "browser.platform": "Win32",
        "os.name":          "Windows",
        "os.type":          "windows",
        "os.description":   "Windows 11 (10.0.22631)",
    },
)

def make_instruments(o11y):
    return {
        "query_count":  o11y.meter.create_counter("search.query_count", description="Search query count"),
        "booking_val":  o11y.meter.create_histogram("booking.value_usd", description="Booking value", unit="USD"),
        "cache_hit":    o11y.meter.create_observable_gauge(
            "offline.cache_hit_ratio",
            description="Offline cache hit ratio",
        ),
    }

def run_scenarios(o11y, platform, instruments):
    tracer = o11y.tracer
    logger = o11y.logger
    results = []
    session_id = uuid.uuid4().hex

    def base_attrs():
        return {"session.id": session_id, "app.platform": platform}

    # ── Scenario 1: Capacitor GPS → nearest airports ──────────────────────────
    try:
        with tracer.start_as_current_span("capacitor.geolocation", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(base_attrs())
            span.set_attribute("capacitor.plugin", "Geolocation")
            span.set_attribute("capacitor.permission", "location")
            time.sleep(random.uniform(0.2, 0.6))
            lat = round(random.uniform(37.0, 47.0), 6)
            lon = round(random.uniform(-122.0, -71.0), 6)
            span.set_attribute("location.latitude", lat)
            span.set_attribute("location.longitude", lon)
            span.set_attribute("location.accuracy_m", round(random.uniform(5, 30), 1))
            # Airport query
            with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as req:
                req.set_attributes(base_attrs())
                req.set_attribute("http.request.method", "GET")
                req.set_attribute("url.full", f"https://api.travelapp.io/v2/airports/nearest?lat={lat}&lon={lon}&radius=200")
                req.set_attribute("server.address", "api.travelapp.io")
                req.set_attribute("service.peer.name", "travelapp-api")
                dur_ms = random.uniform(100, 400)
                time.sleep(dur_ms / 1000)
                req.set_attribute("http.response.status_code", 200)
                req.set_attribute("airports.count", random.randint(3, 12))
            instruments["query_count"].add(1, attributes={"query_type": "nearest_airports", "platform": platform})
        logger.info("GPS location and airport query complete", extra={"lat": lat, "lon": lon, "platform": platform})
        results.append(("Capacitor GPS → nearest airports query", "OK", None))
    except Exception as e:
        results.append(("Capacitor GPS → nearest airports", "ERROR", str(e)))

    # ── Scenario 2: Offline mode — cached data ────────────────────────────────
    try:
        cache_store = "IndexedDB" if platform == "pwa" else "SQLite"
        with tracer.start_as_current_span("offline.cache_read", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(base_attrs())
            span.set_attribute("network.connection.type", "none")
            span.set_attribute("offline.cache_store", cache_store)
            span.set_attribute("offline.cache_key", "flights:JFK-LAX:2024-03-25")
            time.sleep(random.uniform(0.02, 0.08))
            cached_records = random.randint(10, 80)
            span.set_attribute("offline.records_returned", cached_records)
            span.set_attribute("offline.cache_age_s", random.randint(30, 3600))
        logger.info("Offline cache read complete", extra={"store": cache_store, "records": cached_records, "platform": platform})
        results.append(("Offline mode: no network → cached flight data from " + cache_store, "OK", None))
    except Exception as e:
        results.append(("Offline mode: cached data", "ERROR", str(e)))

    # ── Scenario 3: Camera → OCR → passport MRZ ──────────────────────────────
    try:
        with tracer.start_as_current_span("ocr.passport_scan", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(base_attrs())
            span.set_attribute("ocr.engine", "tesseract")
            span.set_attribute("ocr.target", "passport_mrz")
            # Camera capture
            with tracer.start_as_current_span("capacitor.camera", kind=SpanKind.INTERNAL) as cam:
                cam.set_attributes(base_attrs())
                cam.set_attribute("capacitor.plugin", "Camera")
                cam.set_attribute("camera.quality", 90)
                time.sleep(random.uniform(0.15, 0.4))
            # Tesseract OCR
            with tracer.start_as_current_span("ocr.process", kind=SpanKind.INTERNAL) as ocr:
                ocr.set_attributes(base_attrs())
                ocr.set_attribute("ocr.page_seg_mode", 6)
                ocr.set_attribute("ocr.language", "eng")
                time.sleep(random.uniform(0.3, 0.8))
                ocr.set_attribute("ocr.confidence", round(random.uniform(0.88, 0.99), 3))
            span.set_attribute("passport.mrz_parsed", True)
            span.set_attribute("passport.document_type", "P")
        logger.info("Passport MRZ scanned and parsed", extra={"engine": "tesseract", "platform": platform})
        results.append(("Camera → Tesseract OCR → passport MRZ parse", "OK", None))
    except Exception as e:
        results.append(("Camera → OCR → passport MRZ", "ERROR", str(e)))

    # ── Scenario 4: Push notification — price drop alert ──────────────────────
    try:
        with tracer.start_as_current_span("push.price_alert", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(base_attrs())
            notification_id = uuid.uuid4().hex[:8]
            span.set_attribute("push.notification_id", notification_id)
            span.set_attribute("push.type", "price_drop")
            span.set_attribute("push.title", "Price drop! JFK→LAX now $189")
            span.set_attribute("push.deep_link", "travelapp://flights/JFK-LAX/2024-03-28")
            time.sleep(random.uniform(0.05, 0.15))
            # Navigate to flight details
            with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as req:
                req.set_attributes(base_attrs())
                req.set_attribute("http.request.method", "GET")
                req.set_attribute("url.full", "https://api.travelapp.io/v2/flights/JFK-LAX-2024-03-28")
                req.set_attribute("server.address", "api.travelapp.io")
                req.set_attribute("service.peer.name", "travelapp-api")
                dur_ms = random.uniform(80, 300)
                time.sleep(dur_ms / 1000)
                req.set_attribute("http.response.status_code", 200)
            instruments["query_count"].add(1, attributes={"query_type": "flight_detail", "platform": platform})
        logger.info("Price drop push notification handled", extra={"notification_id": notification_id, "platform": platform})
        results.append(("Push notification: price drop alert → flight details deep link", "OK", None))
    except Exception as e:
        results.append(("Push notification: price drop alert", "ERROR", str(e)))

    # ── Scenario 5: In-app browser → Stripe payment ───────────────────────────
    try:
        booking_value = round(random.uniform(189.0, 1200.0), 2)
        with tracer.start_as_current_span("inappbrowser.payment", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(base_attrs())
            span.set_attribute("inappbrowser.url", "https://hotels.partner.io/book?ref=travelapp")
            span.set_attribute("payment.provider", "stripe")
            span.set_attribute("booking.type", "hotel")
            time.sleep(random.uniform(0.3, 0.8))  # Hotel booking page load
            # Stripe payment widget
            with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as pay:
                pay.set_attributes(base_attrs())
                pay.set_attribute("http.request.method", "POST")
                pay.set_attribute("url.full", "https://api.stripe.com/v1/payment_intents")
                pay.set_attribute("server.address", "api.stripe.com")
                pay.set_attribute("service.peer.name", "stripe-api")
                pay.set_attribute("payment.amount_usd", booking_value)
                dur_ms = random.uniform(300, 800)
                time.sleep(dur_ms / 1000)
                pay.set_attribute("http.response.status_code", 200)
                pay.set_attribute("payment.intent_id", f"pi_{uuid.uuid4().hex[:24]}")
            # Webhook confirmation
            with tracer.start_as_current_span("http.client", kind=SpanKind.CLIENT) as webhook:
                webhook.set_attributes(base_attrs())
                webhook.set_attribute("http.request.method", "POST")
                webhook.set_attribute("url.full", "https://api.travelapp.io/v2/webhooks/stripe")
                webhook.set_attribute("server.address", "api.travelapp.io")
                webhook.set_attribute("service.peer.name", "travelapp-api")
                time.sleep(random.uniform(0.05, 0.15))
                webhook.set_attribute("http.response.status_code", 200)
            span.set_attribute("booking.value_usd", booking_value)
            span.set_attribute("booking.confirmed", True)
            instruments["booking_val"].record(booking_value, attributes={"booking_type": "hotel", "platform": platform})
        logger.info("In-app browser hotel booking complete", extra={"booking_value": booking_value, "platform": platform})
        results.append(("In-app browser: hotel booking → Stripe payment → webhook", "OK", None))
    except Exception as e:
        results.append(("In-app browser: hotel booking → Stripe", "ERROR", str(e)))

    # ── Scenario 6: Share extension ───────────────────────────────────────────
    try:
        with tracer.start_as_current_span("share.extension", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(base_attrs())
            share_target = random.choice(["whatsapp", "email", "sms"])
            span.set_attribute("share.target", share_target)
            span.set_attribute("share.content_type", "flight_itinerary")
            span.set_attribute("share.flight", "JFK→LAX AA123 2024-03-28 09:00")
            if platform == "pwa":
                span.set_attribute("share.api", "Web Share API")
            else:
                span.set_attribute("capacitor.plugin", "Share")
            time.sleep(random.uniform(0.05, 0.2))
            span.set_attribute("share.result", "shared")
        logger.info("Share extension complete", extra={"target": share_target, "platform": platform})
        results.append((f"Share extension: flight details → {share_target}", "OK", None))
    except Exception as e:
        results.append(("Share extension", "ERROR", str(e)))

    return results

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"\n[mobile-ionic-travelapp] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Platform: iOS + Android + PWA variants\n")

all_results = []
for platform, o11y in [("ios", o11y_ios), ("android", o11y_android), ("pwa", o11y_pwa)]:
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
o11y_pwa.flush()

ok   = sum(1 for _, s, _ in all_results if s == "OK")
warn = sum(1 for _, s, _ in all_results if s == "WARN")
err  = sum(1 for _, s, _ in all_results if s == "ERROR")
print(f"\n[mobile-ionic-travelapp] Done. {ok} OK | {warn} WARN | {err} ERROR")
print("  Kibana → APM → mobile-ionic-travelapp-ios / -android / -pwa")
print("  Metrics: search.query_count | booking.value_usd | offline.cache_hit_ratio")
