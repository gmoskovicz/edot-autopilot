#!/usr/bin/env python3
"""
Smoke test: Mobile — React Native (ShopApp)

Simulates both iOS and Android variants of a React Native shopping app.
Sends traces + logs + metrics via OTLP/HTTP to Elastic.

Run:
    cd smoke-tests && python3 65-mobile-react-native/smoke.py
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
    "app.name":                 "ShopApp",
    "app.version":              "4.2.1",
    "app.build_number":         "841",
    "telemetry.sdk.name":       "opentelemetry-react-native",
    "telemetry.sdk.version":    "0.4.0",
}

# ── Bootstrap: iOS variant ────────────────────────────────────────────────────
ios_attrs = {
    **COMMON_ATTRS,
    "device.manufacturer":       "Apple",
    "device.model.name":         "iPhone 15 Pro",
    "device.model.identifier":   "iPhone16,1",
    "os.name":                   "iOS",
    "os.version":                "17.2.1",
}
o11y_ios = O11yBootstrap(
    "mobile-rn-shopapp-ios", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=ios_attrs,
)

# ── Bootstrap: Android variant ────────────────────────────────────────────────
android_attrs = {
    **COMMON_ATTRS,
    "device.manufacturer":       "Google",
    "device.model.name":         "Pixel 8",
    "device.model.identifier":   "GC3VE",
    "os.name":                   "Android",
    "os.version":                "14.0",
}
o11y_android = O11yBootstrap(
    "mobile-rn-shopapp-android", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=android_attrs,
)

# ── Metric instruments (iOS) ──────────────────────────────────────────────────
crashes_ios      = o11y_ios.meter.create_counter("app.crashes", description="App crash count")
render_ios       = o11y_ios.meter.create_histogram("screen.render_time_ms", description="Screen render time", unit="ms")
net_dur_ios      = o11y_ios.meter.create_histogram("network.request_duration_ms", description="Network request duration", unit="ms")
sessions_ios     = o11y_ios.meter.create_counter("app.sessions", description="App session count")

# ── Metric instruments (Android) ──────────────────────────────────────────────
crashes_and      = o11y_android.meter.create_counter("app.crashes", description="App crash count")
render_and       = o11y_android.meter.create_histogram("screen.render_time_ms", description="Screen render time", unit="ms")
net_dur_and      = o11y_android.meter.create_histogram("network.request_duration_ms", description="Network request duration", unit="ms")
sessions_and     = o11y_android.meter.create_counter("app.sessions", description="App session count")

# ── Helpers ───────────────────────────────────────────────────────────────────
def make_session_attrs(screen, foreground=True, conn="wifi", carrier=None):
    attrs = {
        "session.id":              uuid.uuid4().hex,
        "user.id":                 f"usr_{uuid.uuid4().hex[:6]}",
        "network.connection.type": conn,
        "screen.name":             screen,
        "app.in_foreground":       foreground,
        "device.screen.width":     390,
        "device.screen.height":    844,
    }
    if conn == "cellular" and carrier:
        attrs["network.carrier.name"] = carrier
    return attrs

def run_scenarios(o11y, platform_label, crashes, render, net_dur, sessions):
    tracer = o11y.tracer
    logger = o11y.logger
    results = []

    sessions.add(1, attributes={"platform": platform_label})

    # ── Scenario 1: App cold start → HomeScreen load ──────────────────────────
    try:
        with tracer.start_as_current_span("app.start", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("HomeScreen"))
            span.set_attribute("startup.type", "cold")
            bundle_ms = random.uniform(180, 320)
            span.set_attribute("js.bundle_parse_ms", round(bundle_ms, 2))
            time.sleep(bundle_ms / 1000)
            with tracer.start_as_current_span("screen.view.HomeScreen") as s2:
                s2.set_attributes(make_session_attrs("HomeScreen"))
                s2.set_attribute("screen.first_render", True)
                native_ms = random.uniform(40, 90)
                time.sleep(native_ms / 1000)
                render.record(native_ms + bundle_ms, attributes={"screen": "HomeScreen", "platform": platform_label})
            logger.info("App cold start complete", extra={"startup_type": "cold", "bundle_ms": round(bundle_ms, 2), "platform": platform_label})
        results.append(("App cold start → HomeScreen", "OK", None))
    except Exception as e:
        results.append(("App cold start → HomeScreen", "ERROR", str(e)))

    # ── Scenario 2: Screen navigation ─────────────────────────────────────────
    try:
        for screen in ["HomeScreen", "ProductDetailScreen"]:
            with tracer.start_as_current_span(f"navigation.transition", kind=SpanKind.INTERNAL) as span:
                span.set_attributes(make_session_attrs(screen))
                span.set_attribute("navigation.from", "HomeScreen" if screen == "ProductDetailScreen" else "LaunchScreen")
                span.set_attribute("navigation.to", screen)
                t_ms = random.uniform(60, 150)
                time.sleep(t_ms / 1000)
                render.record(t_ms, attributes={"screen": screen, "platform": platform_label})
        with tracer.start_as_current_span("user.interaction.AddToCart", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("ProductDetailScreen"))
            span.set_attribute("product.id", f"PROD-{uuid.uuid4().hex[:4].upper()}")
            span.set_attribute("product.price_usd", round(random.uniform(9.99, 299.99), 2))
            time.sleep(random.uniform(0.02, 0.06))
        logger.info("Screen navigation complete", extra={"flow": "home→product→cart", "platform": platform_label})
        results.append(("Screen navigation: Home → Product → Cart", "OK", None))
    except Exception as e:
        results.append(("Screen navigation: Home → Product → Cart", "ERROR", str(e)))

    # ── Scenario 3: Network fetch with retry ──────────────────────────────────
    try:
        with tracer.start_as_current_span("network.fetch", kind=SpanKind.CLIENT) as span:
            attrs = make_session_attrs("HomeScreen", conn="cellular", carrier="Verizon")
            span.set_attributes(attrs)
            span.set_attribute("http.method", "GET")
            span.set_attribute("http.url", "https://api.shopapp.io/v2/recommendations")
            attempt = 0
            success = False
            while attempt < 3 and not success:
                attempt += 1
                dur_ms = random.uniform(120, 800)
                time.sleep(dur_ms / 1000)
                if attempt < 2 and random.random() < 0.4:
                    logger.warning("Network timeout, retrying", extra={"attempt": attempt, "platform": platform_label})
                else:
                    success = True
            span.set_attribute("http.status_code", 200 if success else 504)
            span.set_attribute("http.retry_count", attempt - 1)
            net_dur.record(dur_ms, attributes={"endpoint": "recommendations", "platform": platform_label})
        logger.info("Recommendations fetch complete", extra={"attempts": attempt, "platform": platform_label})
        results.append(("Network fetch: product recommendations", "OK", None))
    except Exception as e:
        results.append(("Network fetch: product recommendations", "ERROR", str(e)))

    # ── Scenario 4: Checkout flow ─────────────────────────────────────────────
    try:
        with tracer.start_as_current_span("screen.view.CartScreen", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("CartScreen"))
            time.sleep(random.uniform(0.05, 0.12))
        with tracer.start_as_current_span("screen.view.PaymentScreen", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("PaymentScreen"))
            time.sleep(random.uniform(0.08, 0.18))
        with tracer.start_as_current_span("user.interaction.SubmitPayment", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("PaymentScreen"))
            span.set_attribute("payment.method", "credit_card")
            dur_ms = random.uniform(300, 900)
            time.sleep(dur_ms / 1000)
            net_dur.record(dur_ms, attributes={"endpoint": "payment", "platform": platform_label})
        with tracer.start_as_current_span("screen.view.OrderConfirmScreen", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("OrderConfirmScreen"))
            span.set_attribute("order.id", f"ORD-{uuid.uuid4().hex[:6].upper()}")
            time.sleep(random.uniform(0.03, 0.08))
        logger.info("Checkout flow complete", extra={"flow": "cart→payment→confirm", "platform": platform_label})
        results.append(("Checkout flow: Cart → Payment → Confirm", "OK", None))
    except Exception as e:
        results.append(("Checkout flow: Cart → Payment → Confirm", "ERROR", str(e)))

    # ── Scenario 5: Push notification → deep link ─────────────────────────────
    try:
        with tracer.start_as_current_span("user.interaction.PushNotificationTap", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("Background", foreground=False))
            span.set_attribute("notification.type", "order_update")
            span.set_attribute("notification.id", uuid.uuid4().hex[:8])
            time.sleep(random.uniform(0.01, 0.03))
        with tracer.start_as_current_span("navigation.transition", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("OrderDetailScreen"))
            span.set_attribute("navigation.from", "Background")
            span.set_attribute("navigation.to", "OrderDetailScreen")
            span.set_attribute("navigation.source", "push_notification")
            deep_link = f"shopapp://orders/{uuid.uuid4().hex[:6]}"
            span.set_attribute("navigation.deep_link", deep_link)
            t_ms = random.uniform(50, 130)
            time.sleep(t_ms / 1000)
            render.record(t_ms, attributes={"screen": "OrderDetailScreen", "platform": platform_label})
        logger.info("Push notification deep link handled", extra={"deep_link": deep_link, "platform": platform_label})
        results.append(("Push notification → OrderDetailScreen deep link", "OK", None))
    except Exception as e:
        results.append(("Push notification → OrderDetailScreen deep link", "ERROR", str(e)))

    # ── Scenario 6: JS crash in payment handler ────────────────────────────────
    try:
        with tracer.start_as_current_span("user.interaction.PaymentHandler", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(make_session_attrs("PaymentScreen"))
            span.set_attribute("payment.method", "apple_pay")
            try:
                time.sleep(random.uniform(0.02, 0.06))
                err = TypeError("Cannot read property 'token' of undefined")
                span.record_exception(err, attributes={"exception.escaped": True})
                span.set_status(StatusCode.ERROR, str(err))
                crashes.add(1, attributes={"crash.type": "TypeError", "platform": platform_label})
                logger.error(
                    "JS crash in payment handler — caught by error boundary",
                    extra={"error.type": "TypeError", "screen": "PaymentScreen", "platform": platform_label},
                )
                results.append(("JS crash: TypeError in payment handler", "WARN", "Caught by error boundary"))
            except Exception:
                pass
    except Exception as e:
        results.append(("JS crash: TypeError in payment handler", "ERROR", str(e)))

    return results

# ── Run scenarios for both platforms ─────────────────────────────────────────
print(f"\n[mobile-rn-shopapp] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Platform: iOS + Android variants\n")

all_results = []
for label, o11y, crashes, render, net_dur, sessions in [
    ("ios",     o11y_ios,     crashes_ios, render_ios, net_dur_ios, sessions_ios),
    ("android", o11y_android, crashes_and, render_and, net_dur_and, sessions_and),
]:
    print(f"  -- {label.upper()} --")
    res = run_scenarios(o11y, label, crashes, render, net_dur, sessions)
    for scenario, status, note in res:
        icon = "OK" if status == "OK" else ("WARN" if status == "WARN" else "ERROR")
        symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
        note_str = f"  ({note})" if note else ""
        print(f"    {symbol} [{label}] {scenario}{note_str}")
    all_results.extend(res)

o11y_ios.flush()
o11y_android.flush()

ok    = sum(1 for _, s, _ in all_results if s == "OK")
warn  = sum(1 for _, s, _ in all_results if s == "WARN")
err   = sum(1 for _, s, _ in all_results if s == "ERROR")
print(f"\n[mobile-rn-shopapp] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → mobile-rn-shopapp-ios / mobile-rn-shopapp-android")
print(f"  Metrics: app.crashes | screen.render_time_ms | network.request_duration_ms | app.sessions")
