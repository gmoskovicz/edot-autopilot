#!/usr/bin/env python3
"""
Smoke test: Web — Angular CRM (client + Spring Boot API)

Simulates browser RUM traces from an Angular 17 CRM application using the
OpenTelemetry Web SDK pattern, plus server-side spans from the Spring Boot
backend API. Covers bootstrap, HTTP interceptors, Angular Universal SSR,
reactive forms, lazy module loading, and Signals with change detection.

Run:
    cd smoke-tests && python3 74-web-angular/smoke.py
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

# ── Angular client bootstrap ───────────────────────────────────────────────────
angular_attrs = {
    "browser.name":       "Edge",
    "browser.version":    "120.0",
    "browser.platform":   "Win32",
    "framework":          "angular",
    "angular.version":    "17.0.0",
    "telemetry.sdk.name": "opentelemetry-js-web",
}
o11y_angular = O11yBootstrap(
    "web-angular-crm-client", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=angular_attrs,
)

# ── Spring Boot API bootstrap ──────────────────────────────────────────────────
spring_attrs = {
    "telemetry.sdk.name": "opentelemetry-java",
    "framework":          "spring-boot",
    "spring.version":     "3.2.0",
    "java.version":       "21",
}
o11y_api = O11yBootstrap(
    "web-angular-crm-api", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=spring_attrs,
)

# ── Metrics ────────────────────────────────────────────────────────────────────
lcp_hist       = o11y_angular.meter.create_histogram("webvitals.lcp",      description="Largest Contentful Paint",  unit="ms")
fid_hist       = o11y_angular.meter.create_histogram("webvitals.fid",      description="First Input Delay",         unit="ms")
cls_hist       = o11y_angular.meter.create_histogram("webvitals.cls",      description="Cumulative Layout Shift")
ttfb_hist      = o11y_angular.meter.create_histogram("webvitals.ttfb",     description="Time to First Byte",        unit="ms")
page_views     = o11y_angular.meter.create_counter("page.view",            description="Page view count")
fetch_dur_hist = o11y_angular.meter.create_histogram("fetch.duration_ms",  description="HTTP request duration",     unit="ms")
bootstrap_hist = o11y_angular.meter.create_histogram("angular.bootstrap_ms", description="Angular bootstrap time", unit="ms")

propagator = TraceContextTextMapPropagator()

def inject_traceparent(span):
    carrier = {}
    ctx = propagate.set_span_in_context(span)
    propagator.inject(carrier, context=ctx)
    return carrier

def extract_context(carrier):
    return propagator.extract(carrier)

def session_attrs(component, route):
    return {
        "session.id":           uuid.uuid4().hex,
        "user.id":              f"usr_{uuid.uuid4().hex[:8]}",
        "angular.component":    component,
        "angular.route":        route,
    }

print(f"\n[web-angular-crm] Sending browser RUM + Spring Boot API traces to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Services: web-angular-crm-client (Angular 17) + web-angular-crm-api (Spring Boot)\n")

results = []

# ── Scenario 1: Angular bootstrap ─────────────────────────────────────────────
try:
    ttfb_ms      = random.uniform(50, 800)
    lcp_ms       = random.uniform(800, 4000)
    cls_val      = random.uniform(0.001, 0.35)
    bootstrap_ms = random.uniform(200, 600)

    with o11y_angular.tracer.start_as_current_span("angular.bootstrap", kind=SpanKind.INTERNAL) as boot_span:
        attrs = session_attrs("AppComponent", "/")
        boot_span.set_attributes(attrs)
        boot_span.set_attribute("angular.module",      "AppModule")
        boot_span.set_attribute("bootstrap.type",      "platformBrowserDynamic")
        boot_span.set_attribute("webvitals.ttfb_ms",   round(ttfb_ms, 2))
        boot_span.set_attribute("webvitals.lcp_ms",    round(lcp_ms, 2))
        boot_span.set_attribute("webvitals.cls_score", round(cls_val, 4))
        time.sleep(bootstrap_ms / 1000)

        with o11y_angular.tracer.start_as_current_span("angular.router.navigate", kind=SpanKind.INTERNAL) as nav_span:
            nav_span.set_attribute("angular.module",   "AppModule")
            nav_span.set_attribute("angular.route",    "/contacts")
            nav_span.set_attribute("angular.guard",    "AuthGuard")
            time.sleep(random.uniform(0.02, 0.06))

    page_views.add(1, attributes={"page.route": "/contacts"})
    bootstrap_hist.record(bootstrap_ms, attributes={"angular.module": "AppModule"})
    lcp_hist.record(lcp_ms, attributes={"page.route": "/"})
    cls_hist.record(cls_val, attributes={"page.route": "/"})
    ttfb_hist.record(ttfb_ms, attributes={"page.route": "/"})
    o11y_angular.logger.info("Angular bootstrap complete", extra={"module": "AppModule", "bootstrap_ms": round(bootstrap_ms, 2)})
    results.append(("Bootstrap: platformBrowserDynamic → AppModule init → Router navigate", "OK", None))
except Exception as e:
    results.append(("Bootstrap: platformBrowserDynamic → AppModule init → Router navigate", "ERROR", str(e)))

# ── Scenario 2: HTTP Interceptor — auth header → API call → transform ──────────
try:
    fid_ms = random.uniform(10, 500)
    with o11y_angular.tracer.start_as_current_span("angular.http.GET", kind=SpanKind.CLIENT) as http_span:
        attrs = session_attrs("ContactListComponent", "/contacts")
        http_span.set_attributes(attrs)
        http_span.set_attribute("angular.interceptor",  "AuthInterceptor")
        http_span.set_attribute("http.url",             "https://api.crm.example.com/api/contacts")
        http_span.set_attribute("http.method",          "GET")
        http_span.set_attribute("http.status_code",     200)
        http_span.set_attribute("auth.header_injected", True)
        http_span.set_attribute("webvitals.fid_ms",     round(fid_ms, 2))
        carrier = inject_traceparent(http_span)

        fetch_start = time.time()
        time.sleep(random.uniform(0.06, 0.18))
        fetch_ms = (time.time() - fetch_start) * 1000
        fetch_dur_hist.record(fetch_ms, attributes={"http.route": "/api/contacts"})

    # Spring Boot handler
    remote_ctx = extract_context(carrier)
    with o11y_api.tracer.start_as_current_span(
        "GET /api/contacts", kind=SpanKind.SERVER, context=remote_ctx
    ) as srv_span:
        srv_span.set_attribute("http.route",       "/api/contacts")
        srv_span.set_attribute("http.method",      "GET")
        srv_span.set_attribute("http.status_code", 200)
        srv_span.set_attribute("framework.name",   "spring-boot")
        with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system",    "postgresql")
            db_span.set_attribute("db.statement", "SELECT c.id, c.name, c.email, c.phone FROM contacts c WHERE c.account_id = ? ORDER BY c.name")
            time.sleep(random.uniform(0.01, 0.04))

    fid_hist.record(fid_ms, attributes={"page.route": "/contacts"})
    o11y_angular.logger.info("HTTP interceptor call complete", extra={"route": "/api/contacts", "interceptor": "AuthInterceptor"})
    results.append(("HTTP Interceptor: attach auth header → API call → response transform", "OK", None))
except Exception as e:
    results.append(("HTTP Interceptor: attach auth header → API call → response transform", "ERROR", str(e)))

# ── Scenario 3: Angular Universal SSR → TransferState → client rehydrate ───────
try:
    render_ms = random.uniform(40, 150)

    # SSR render (runs on Node server)
    with o11y_api.tracer.start_as_current_span("angular.ssr.render", kind=SpanKind.SERVER) as ssr_span:
        ssr_span.set_attribute("angular.module",   "AppServerModule")
        ssr_span.set_attribute("http.route",       "/contacts/456")
        ssr_span.set_attribute("http.method",      "GET")
        ssr_span.set_attribute("http.status_code", 200)
        ssr_span.set_attribute("ssr.transfer_state", True)
        carrier = inject_traceparent(ssr_span)
        with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system",    "postgresql")
            db_span.set_attribute("db.statement", "SELECT * FROM contacts WHERE id = ?")
            time.sleep(random.uniform(0.01, 0.03))
        time.sleep(render_ms / 1000)

    # Client rehydration (linked via traceparent)
    remote_ctx = extract_context(carrier)
    hydration_ms = random.uniform(30, 100)
    with o11y_angular.tracer.start_as_current_span(
        "angular.bootstrap", kind=SpanKind.INTERNAL, context=remote_ctx
    ) as hyd_span:
        hyd_span.set_attribute("angular.module",        "AppModule")
        hyd_span.set_attribute("ssr.rehydration",       True)
        hyd_span.set_attribute("ssr.transfer_state",    True)
        hyd_span.set_attribute("angular.component",     "ContactDetailComponent")
        time.sleep(hydration_ms / 1000)

    page_views.add(1, attributes={"page.route": "/contacts/456"})
    o11y_angular.logger.info("SSR rehydration complete", extra={"route": "/contacts/456", "render_ms": round(render_ms, 2)})
    results.append(("Angular Universal SSR: render → TransferState → client rehydrate", "OK", None))
except Exception as e:
    results.append(("Angular Universal SSR: render → TransferState → client rehydrate", "ERROR", str(e)))

# ── Scenario 4: ReactiveForm — async validator → submit ───────────────────────
try:
    # Async email uniqueness validator
    with o11y_angular.tracer.start_as_current_span("angular.http.GET", kind=SpanKind.CLIENT) as validator_span:
        attrs = session_attrs("ContactFormComponent", "/contacts/new")
        validator_span.set_attributes(attrs)
        validator_span.set_attribute("angular.interceptor", "AuthInterceptor")
        validator_span.set_attribute("http.url",            "https://api.crm.example.com/api/contacts/check-email")
        validator_span.set_attribute("http.method",         "GET")
        validator_span.set_attribute("http.status_code",    200)
        validator_span.set_attribute("form.validator",      "emailUnique")
        carrier = inject_traceparent(validator_span)
        time.sleep(random.uniform(0.04, 0.12))

    # Spring Boot email check
    remote_ctx = extract_context(carrier)
    with o11y_api.tracer.start_as_current_span(
        "GET /api/contacts/check-email", kind=SpanKind.SERVER, context=remote_ctx
    ) as srv_span:
        srv_span.set_attribute("http.route",       "/api/contacts/check-email")
        srv_span.set_attribute("http.method",      "GET")
        srv_span.set_attribute("http.status_code", 200)
        srv_span.set_attribute("framework.name",   "spring-boot")
        with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system",    "postgresql")
            db_span.set_attribute("db.statement", "SELECT COUNT(*) FROM contacts WHERE email = ?")
            time.sleep(random.uniform(0.005, 0.02))

    # Form submit
    with o11y_angular.tracer.start_as_current_span("angular.form.submit", kind=SpanKind.INTERNAL) as form_span:
        form_span.set_attribute("angular.component", "ContactFormComponent")
        form_span.set_attribute("form.valid",        True)
        form_span.set_attribute("angular.route",     "/contacts/new")

        with o11y_angular.tracer.start_as_current_span("angular.http.POST", kind=SpanKind.CLIENT) as post_span:
            post_span.set_attribute("angular.interceptor", "AuthInterceptor")
            post_span.set_attribute("http.url",            "https://api.crm.example.com/api/contacts")
            post_span.set_attribute("http.method",         "POST")
            post_span.set_attribute("http.status_code",    201)
            carrier2 = inject_traceparent(post_span)
            time.sleep(random.uniform(0.06, 0.15))

        remote_ctx2 = extract_context(carrier2)
        with o11y_api.tracer.start_as_current_span(
            "POST /api/contacts", kind=SpanKind.SERVER, context=remote_ctx2
        ) as srv_span:
            srv_span.set_attribute("http.route",       "/api/contacts")
            srv_span.set_attribute("http.method",      "POST")
            srv_span.set_attribute("http.status_code", 201)
            srv_span.set_attribute("framework.name",   "spring-boot")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system",    "postgresql")
                db_span.set_attribute("db.statement", "INSERT INTO contacts (account_id, name, email, phone) VALUES (?, ?, ?, ?) RETURNING id")
                time.sleep(random.uniform(0.01, 0.04))

    o11y_angular.logger.info("Contact form submitted", extra={"route": "/contacts/new", "validator": "emailUnique"})
    results.append(("Form validation: ReactiveForm → async validator (email unique) → submit", "OK", None))
except Exception as e:
    results.append(("Form validation: ReactiveForm → async validator (email unique) → submit", "ERROR", str(e)))

# ── Scenario 5: Lazy module load ───────────────────────────────────────────────
try:
    chunk_ms = random.uniform(100, 500)
    with o11y_angular.tracer.start_as_current_span("angular.lazy_module.load", kind=SpanKind.INTERNAL) as lazy_span:
        attrs = session_attrs("RouterView", "/reports")
        lazy_span.set_attributes(attrs)
        lazy_span.set_attribute("angular.module",     "LazyFeatureModule")
        lazy_span.set_attribute("chunk.name",         "reports-module.chunk.js")
        lazy_span.set_attribute("chunk.download_ms",  round(chunk_ms, 2))
        lazy_span.set_attribute("angular.route",      "/reports")
        time.sleep(chunk_ms / 1000)

        with o11y_angular.tracer.start_as_current_span("angular.router.navigate", kind=SpanKind.INTERNAL) as nav_span:
            nav_span.set_attribute("angular.module",  "LazyFeatureModule")
            nav_span.set_attribute("angular.route",   "/reports")
            nav_span.set_attribute("angular.guard",   "PermissionGuard")
            time.sleep(random.uniform(0.01, 0.03))

    page_views.add(1, attributes={"page.route": "/reports"})
    o11y_angular.logger.info("Lazy module loaded", extra={"module": "LazyFeatureModule", "chunk_ms": round(chunk_ms, 2)})
    results.append(("Lazy module: loadChildren → chunk download → feature module activate", "OK", None))
except Exception as e:
    results.append(("Lazy module: loadChildren → chunk download → feature module activate", "ERROR", str(e)))

# ── Scenario 6: Signals + OnPush change detection ─────────────────────────────
try:
    with o11y_angular.tracer.start_as_current_span("angular.router.navigate", kind=SpanKind.INTERNAL) as nav_span:
        attrs = session_attrs("ContactListComponent", "/contacts")
        nav_span.set_attributes(attrs)
        nav_span.set_attribute("angular.route",   "/contacts")
        nav_span.set_attribute("angular.guard",   "AuthGuard")
        time.sleep(random.uniform(0.01, 0.03))

        # Signal computed triggers OnPush re-render
        with o11y_angular.tracer.start_as_current_span("angular.http.GET", kind=SpanKind.CLIENT) as sig_span:
            sig_span.set_attribute("angular.component",      "ContactListComponent")
            sig_span.set_attribute("angular.signals",        True)
            sig_span.set_attribute("angular.change_detection", "OnPush")
            sig_span.set_attribute("http.url",               "https://api.crm.example.com/api/contacts?page=2")
            sig_span.set_attribute("http.method",            "GET")
            sig_span.set_attribute("http.status_code",       200)
            sig_span.set_attribute("angular.interceptor",    "AuthInterceptor")
            carrier = inject_traceparent(sig_span)
            time.sleep(random.uniform(0.04, 0.12))

        remote_ctx = extract_context(carrier)
        with o11y_api.tracer.start_as_current_span(
            "GET /api/contacts", kind=SpanKind.SERVER, context=remote_ctx
        ) as srv_span:
            srv_span.set_attribute("http.route",       "/api/contacts")
            srv_span.set_attribute("http.method",      "GET")
            srv_span.set_attribute("http.status_code", 200)
            srv_span.set_attribute("framework.name",   "spring-boot")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system",    "postgresql")
                db_span.set_attribute("db.statement", "SELECT c.id, c.name, c.email FROM contacts c WHERE c.account_id = ? ORDER BY c.name LIMIT ? OFFSET ?")
                time.sleep(random.uniform(0.01, 0.03))

    o11y_angular.logger.info("Signals OnPush re-render complete", extra={"component": "ContactListComponent", "signals": True})
    results.append(("Signals + change detection: computed signal → OnPush component re-render", "OK", None))
except Exception as e:
    results.append(("Signals + change detection: computed signal → OnPush component re-render", "ERROR", str(e)))

# ── Flush all ─────────────────────────────────────────────────────────────────
o11y_angular.flush()
o11y_api.flush()

# ── Summary ───────────────────────────────────────────────────────────────────
ok   = sum(1 for _, s, _ in results if s == "OK")
warn = sum(1 for _, s, _ in results if s == "WARN")
err  = sum(1 for _, s, _ in results if s == "ERROR")

for scenario, status, note in results:
    symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
    note_str = f"  ({note})" if note else ""
    print(f"  {symbol} {scenario}{note_str}")

print(f"\n[web-angular-crm] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → web-angular-crm-client | web-angular-crm-api")
print(f"  Metrics: webvitals.lcp | webvitals.fid | webvitals.cls | page.view | fetch.duration_ms | angular.bootstrap_ms")
