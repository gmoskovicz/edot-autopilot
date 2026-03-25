#!/usr/bin/env python3
"""
Smoke test: Web — Vue 3 Dashboard (client + Laravel API)

Simulates browser RUM traces from a Vue 3 SPA using Pinia for state management
and Vue Router for navigation. Also emits server-side spans for the Laravel
API that the Vue app calls. Covers component lifecycle, store actions,
router guards, WebSocket events, error boundaries, and Suspense.

Run:
    cd smoke-tests && python3 73-web-vue/smoke.py
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

from opentelemetry import propagate, context
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

# ── Vue client bootstrap ───────────────────────────────────────────────────────
vue_attrs = {
    "browser.name":       "Firefox",
    "browser.version":    "121.0",
    "browser.platform":   "Linux",
    "framework":          "vue",
    "vue.version":        "3.4.0",
    "telemetry.sdk.name": "opentelemetry-js-web",
}
o11y_vue = O11yBootstrap(
    "web-vue-dashboard-client", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=vue_attrs,
)

# ── Laravel API bootstrap ──────────────────────────────────────────────────────
laravel_attrs = {
    "telemetry.sdk.name": "opentelemetry-php",
    "framework":          "laravel",
    "php.version":        "8.2.0",
}
o11y_api = O11yBootstrap(
    "web-vue-dashboard-api", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=laravel_attrs,
)

# ── Metrics ────────────────────────────────────────────────────────────────────
lcp_hist       = o11y_vue.meter.create_histogram("webvitals.lcp",         description="Largest Contentful Paint",  unit="ms")
fid_hist       = o11y_vue.meter.create_histogram("webvitals.fid",         description="First Input Delay",         unit="ms")
cls_hist       = o11y_vue.meter.create_histogram("webvitals.cls",         description="Cumulative Layout Shift")
ttfb_hist      = o11y_vue.meter.create_histogram("webvitals.ttfb",        description="Time to First Byte",        unit="ms")
page_views     = o11y_vue.meter.create_counter("page.view",               description="Page view count")
fetch_dur_hist = o11y_vue.meter.create_histogram("fetch.duration_ms",     description="Fetch duration",            unit="ms")
ws_msg_counter = o11y_vue.meter.create_counter("websocket.messages",      description="WebSocket messages received")

propagator = TraceContextTextMapPropagator()

def inject_traceparent(span):
    carrier = {}
    ctx = propagate.set_span_in_context(span)
    propagator.inject(carrier, context=ctx)
    return carrier

def extract_context(carrier):
    return propagator.extract(carrier)

def session_attrs(component, route_to):
    return {
        "session.id":          uuid.uuid4().hex,
        "user.id":             f"usr_{uuid.uuid4().hex[:8]}",
        "vue.component.name":  component,
        "vue.router.to":       route_to,
    }

print(f"\n[web-vue-dashboard] Sending browser RUM + Laravel API traces to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Services: web-vue-dashboard-client (Vue 3) + web-vue-dashboard-api (Laravel)\n")

results = []

# ── Scenario 1: Dashboard mount ────────────────────────────────────────────────
try:
    ttfb_ms = random.uniform(50, 800)
    lcp_ms  = random.uniform(800, 4000)
    cls_val = random.uniform(0.001, 0.35)

    with o11y_vue.tracer.start_as_current_span("vue.app.mount", kind=SpanKind.INTERNAL) as mount_span:
        attrs = session_attrs("App", "/dashboard")
        mount_span.set_attributes(attrs)
        mount_span.set_attribute("vue.router.from",  "/")
        mount_span.set_attribute("webvitals.ttfb_ms", round(ttfb_ms, 2))
        mount_span.set_attribute("webvitals.lcp_ms",  round(lcp_ms, 2))
        mount_span.set_attribute("webvitals.cls_score", round(cls_val, 4))
        time.sleep(ttfb_ms / 1000)

        with o11y_vue.tracer.start_as_current_span("vue.router.navigate", kind=SpanKind.INTERNAL) as nav_span:
            nav_span.set_attribute("vue.router.from",  "/")
            nav_span.set_attribute("vue.router.to",    "/dashboard")
            nav_span.set_attribute("vue.router.guard", "beforeEach")
            time.sleep(random.uniform(0.01, 0.03))

        with o11y_vue.tracer.start_as_current_span("vue.component.setup", kind=SpanKind.INTERNAL) as setup_span:
            setup_span.set_attribute("vue.component.name", "DashboardView")
            time.sleep(random.uniform(0.02, 0.06))

        # Initial API call from dashboard
        fetch_start = time.time()
        with o11y_vue.tracer.start_as_current_span("fetch.GET /api/dashboard", kind=SpanKind.CLIENT) as fetch_span:
            fetch_span.set_attribute("http.url",         "https://api.dashboard.example.com/api/dashboard")
            fetch_span.set_attribute("http.method",      "GET")
            fetch_span.set_attribute("http.status_code", 200)
            carrier = inject_traceparent(fetch_span)
            time.sleep(random.uniform(0.06, 0.18))
        fetch_ms = (time.time() - fetch_start) * 1000
        fetch_dur_hist.record(fetch_ms, attributes={"http.route": "/api/dashboard"})

        # Laravel handler
        remote_ctx = extract_context(carrier)
        with o11y_api.tracer.start_as_current_span(
            "GET /api/dashboard", kind=SpanKind.SERVER, context=remote_ctx
        ) as srv_span:
            srv_span.set_attribute("http.route",       "/api/dashboard")
            srv_span.set_attribute("http.method",      "GET")
            srv_span.set_attribute("http.status_code", 200)
            srv_span.set_attribute("framework.name",   "laravel")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system",    "mysql")
                db_span.set_attribute("db.statement", "SELECT * FROM dashboard_widgets WHERE user_id = ? ORDER BY position")
                time.sleep(random.uniform(0.01, 0.04))

    page_views.add(1, attributes={"page.route": "/dashboard"})
    lcp_hist.record(lcp_ms, attributes={"page.route": "/dashboard"})
    cls_hist.record(cls_val, attributes={"page.route": "/dashboard"})
    ttfb_hist.record(ttfb_ms, attributes={"page.route": "/dashboard"})
    o11y_vue.logger.info("Dashboard mounted", extra={"component": "DashboardView", "route": "/dashboard"})
    results.append(("Dashboard mount: Vue app create → router → setup → API calls", "OK", None))
except Exception as e:
    results.append(("Dashboard mount: Vue app create → router → setup → API calls", "ERROR", str(e)))

# ── Scenario 2: Pinia store action → API GET → reactive update ────────────────
try:
    with o11y_vue.tracer.start_as_current_span("pinia.action", kind=SpanKind.INTERNAL) as pinia_span:
        attrs = session_attrs("UserCard", "/dashboard")
        pinia_span.set_attributes(attrs)
        pinia_span.set_attribute("pinia.store",  "userStore")
        pinia_span.set_attribute("pinia.action", "fetchUser")
        time.sleep(random.uniform(0.005, 0.015))

        fetch_start = time.time()
        with o11y_vue.tracer.start_as_current_span("fetch.GET /api/user", kind=SpanKind.CLIENT) as fetch_span:
            fetch_span.set_attribute("http.url",         "https://api.dashboard.example.com/api/user")
            fetch_span.set_attribute("http.method",      "GET")
            fetch_span.set_attribute("http.status_code", 200)
            carrier = inject_traceparent(fetch_span)
            time.sleep(random.uniform(0.04, 0.12))
        fetch_ms = (time.time() - fetch_start) * 1000
        fetch_dur_hist.record(fetch_ms, attributes={"http.route": "/api/user"})

        # Laravel
        remote_ctx = extract_context(carrier)
        with o11y_api.tracer.start_as_current_span(
            "GET /api/user", kind=SpanKind.SERVER, context=remote_ctx
        ) as srv_span:
            srv_span.set_attribute("http.route",       "/api/user")
            srv_span.set_attribute("http.method",      "GET")
            srv_span.set_attribute("http.status_code", 200)
            srv_span.set_attribute("framework.name",   "laravel")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system",    "mysql")
                db_span.set_attribute("db.statement", "SELECT id, name, email, avatar FROM users WHERE id = ?")
                time.sleep(random.uniform(0.008, 0.025))

        # Commit mutation (reactive update)
        with o11y_vue.tracer.start_as_current_span("pinia.action", kind=SpanKind.INTERNAL) as commit_span:
            commit_span.set_attribute("pinia.store",  "userStore")
            commit_span.set_attribute("pinia.action", "$patch")
            time.sleep(random.uniform(0.001, 0.005))

    o11y_vue.logger.info("Pinia user store updated", extra={"store": "userStore", "action": "fetchUser"})
    results.append(("Pinia store action: fetchUserData → API GET → commit mutation → reactive update", "OK", None))
except Exception as e:
    results.append(("Pinia store action: fetchUserData → API GET → commit mutation → reactive update", "ERROR", str(e)))

# ── Scenario 3: Vue Router navigation guard ───────────────────────────────────
try:
    with o11y_vue.tracer.start_as_current_span("vue.router.navigate", kind=SpanKind.INTERNAL) as nav_span:
        attrs = session_attrs("RouterView", "/settings")
        nav_span.set_attributes(attrs)
        nav_span.set_attribute("vue.router.from",  "/dashboard")
        nav_span.set_attribute("vue.router.to",    "/settings")
        nav_span.set_attribute("vue.router.guard", "beforeEach")

        # Auth check
        with o11y_vue.tracer.start_as_current_span("pinia.action", kind=SpanKind.INTERNAL) as auth_span:
            auth_span.set_attribute("pinia.store",  "userStore")
            auth_span.set_attribute("pinia.action", "checkAuth")
            time.sleep(random.uniform(0.005, 0.015))

        # Load user for route
        with o11y_vue.tracer.start_as_current_span("pinia.action", kind=SpanKind.INTERNAL) as load_span:
            load_span.set_attribute("pinia.store",  "dashboardStore")
            load_span.set_attribute("pinia.action", "refreshDashboard")
            time.sleep(random.uniform(0.01, 0.03))

        # Proceed to route — component setup
        with o11y_vue.tracer.start_as_current_span("vue.component.setup", kind=SpanKind.INTERNAL) as setup_span:
            setup_span.set_attribute("vue.component.name", "SettingsView")
            time.sleep(random.uniform(0.02, 0.05))

    page_views.add(1, attributes={"page.route": "/settings"})
    o11y_vue.logger.info("Router guard navigation complete", extra={"from": "/dashboard", "to": "/settings"})
    results.append(("Vue Router guard: check auth → load user → proceed to route", "OK", None))
except Exception as e:
    results.append(("Vue Router guard: check auth → load user → proceed to route", "ERROR", str(e)))

# ── Scenario 4: WebSocket real-time update ─────────────────────────────────────
try:
    with o11y_vue.tracer.start_as_current_span("websocket.connect", kind=SpanKind.CLIENT) as ws_span:
        attrs = session_attrs("DashboardView", "/dashboard")
        ws_span.set_attributes(attrs)
        ws_span.set_attribute("websocket.url",      "wss://ws.dashboard.example.com/live")
        ws_span.set_attribute("websocket.protocol", "v1")
        time.sleep(random.uniform(0.02, 0.08))

    # Receive a few real-time events
    for i in range(3):
        with o11y_vue.tracer.start_as_current_span("websocket.message", kind=SpanKind.INTERNAL) as msg_span:
            msg_span.set_attribute("websocket.event",        "metric.update")
            msg_span.set_attribute("websocket.payload_size", random.randint(120, 800))
            msg_span.set_attribute("pinia.store",            "dashboardStore")
            msg_span.set_attribute("pinia.action",           "refreshDashboard")
            time.sleep(random.uniform(0.005, 0.02))
        ws_msg_counter.add(1, attributes={"websocket.event": "metric.update"})

    o11y_vue.logger.info("WebSocket events received", extra={"events": 3, "channel": "metric.update"})
    results.append(("Real-time: WebSocket connect → metric.update events → reactive state", "OK", None))
except Exception as e:
    results.append(("Real-time: WebSocket connect → metric.update events → reactive state", "ERROR", str(e)))

# ── Scenario 5: Error boundary — component throws ─────────────────────────────
try:
    with o11y_vue.tracer.start_as_current_span("vue.component.setup", kind=SpanKind.INTERNAL) as setup_span:
        attrs = session_attrs("ChartWidget", "/dashboard")
        setup_span.set_attributes(attrs)
        setup_span.set_attribute("vue.component.name", "ChartWidget")
        time.sleep(random.uniform(0.01, 0.03))
        err = RuntimeError("Cannot read properties of undefined (reading 'data')")
        setup_span.record_exception(err, attributes={"exception.escaped": True})
        setup_span.set_status(StatusCode.ERROR, str(err))

    # onErrorCaptured boundary catches it
    with o11y_vue.tracer.start_as_current_span("vue.component.setup", kind=SpanKind.INTERNAL) as boundary_span:
        boundary_span.set_attribute("vue.component.name",  "ErrorBoundary")
        boundary_span.set_attribute("error.captured",      True)
        boundary_span.set_attribute("error.component",     "ChartWidget")
        boundary_span.set_attribute("error.recovered",     True)
        time.sleep(random.uniform(0.005, 0.015))

    o11y_vue.logger.error(
        "Component error captured by boundary",
        extra={"component": "ChartWidget", "error": "Cannot read properties of undefined (reading 'data')"}
    )
    results.append(("Error boundary: component throws → onErrorCaptured → logged to Elastic", "WARN", "Caught by ErrorBoundary"))
except Exception as e:
    results.append(("Error boundary: component throws → onErrorCaptured → logged to Elastic", "ERROR", str(e)))

# ── Scenario 6: Suspense — async component ───────────────────────────────────
try:
    with o11y_vue.tracer.start_as_current_span("vue.component.setup", kind=SpanKind.INTERNAL) as suspense_span:
        attrs = session_attrs("AsyncDataTable", "/dashboard")
        suspense_span.set_attributes(attrs)
        suspense_span.set_attribute("vue.component.name",  "AsyncDataTable")
        suspense_span.set_attribute("vue.suspense",        True)
        suspense_span.set_attribute("vue.loading_state",   "loading")

        # Async data load
        fetch_start = time.time()
        with o11y_vue.tracer.start_as_current_span("fetch.GET /api/dashboard", kind=SpanKind.CLIENT) as fetch_span:
            fetch_span.set_attribute("http.url",         "https://api.dashboard.example.com/api/analytics")
            fetch_span.set_attribute("http.method",      "GET")
            fetch_span.set_attribute("http.status_code", 200)
            carrier = inject_traceparent(fetch_span)
            time.sleep(random.uniform(0.08, 0.22))
        fetch_ms = (time.time() - fetch_start) * 1000
        fetch_dur_hist.record(fetch_ms, attributes={"http.route": "/api/analytics"})

        # Laravel
        remote_ctx = extract_context(carrier)
        with o11y_api.tracer.start_as_current_span(
            "GET /api/analytics", kind=SpanKind.SERVER, context=remote_ctx
        ) as srv_span:
            srv_span.set_attribute("http.route",       "/api/analytics")
            srv_span.set_attribute("http.method",      "GET")
            srv_span.set_attribute("http.status_code", 200)
            srv_span.set_attribute("framework.name",   "laravel")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system",    "mysql")
                db_span.set_attribute("db.statement", "SELECT date, metric, value FROM analytics WHERE user_id = ? AND date >= ? ORDER BY date DESC")
                time.sleep(random.uniform(0.02, 0.06))

        suspense_span.set_attribute("vue.loading_state", "resolved")

    o11y_vue.logger.info("Async component resolved", extra={"component": "AsyncDataTable"})
    results.append(("Suspense: async component → loading state → resolved → rendered", "OK", None))
except Exception as e:
    results.append(("Suspense: async component → loading state → resolved → rendered", "ERROR", str(e)))

# ── Flush all ─────────────────────────────────────────────────────────────────
o11y_vue.flush()
o11y_api.flush()

# ── Summary ───────────────────────────────────────────────────────────────────
ok   = sum(1 for _, s, _ in results if s == "OK")
warn = sum(1 for _, s, _ in results if s == "WARN")
err  = sum(1 for _, s, _ in results if s == "ERROR")

for scenario, status, note in results:
    symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
    note_str = f"  ({note})" if note else ""
    print(f"  {symbol} {scenario}{note_str}")

print(f"\n[web-vue-dashboard] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → web-vue-dashboard-client | web-vue-dashboard-api")
print(f"  Metrics: webvitals.lcp | webvitals.fid | webvitals.cls | page.view | fetch.duration_ms | websocket.messages")
