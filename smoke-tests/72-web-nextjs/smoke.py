#!/usr/bin/env python3
"""
Smoke test: Web — Next.js SaaS (SSR + Client hydration)

Simulates both SSR server spans and client-side hydration spans for a Next.js
14 SaaS application. Shows frontend→backend trace linkage via W3C traceparent.
Covers getServerSideProps, Server Actions, API routes, ISR, middleware, and
Edge runtime scenarios.

Run:
    cd smoke-tests && python3 72-web-nextjs/smoke.py
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
from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

# ── SSR server bootstrap ───────────────────────────────────────────────────────
ssr_attrs = {
    "telemetry.sdk.name":     "opentelemetry-node",
    "telemetry.sdk.language": "javascript",
    "framework":              "nextjs",
    "nextjs.version":         "14.0.4",
    "node.version":           "20.10.0",
}
o11y_ssr = O11yBootstrap(
    "web-nextjs-saas-ssr", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=ssr_attrs,
)

# ── Client-side hydration bootstrap ───────────────────────────────────────────
client_attrs = {
    "browser.name":           "Safari",
    "browser.version":        "17.2",
    "browser.platform":       "MacIntel",
    "browser.mobile":         False,
    "telemetry.sdk.name":     "opentelemetry-js-web",
    "telemetry.sdk.language": "javascript",
}
o11y_client = O11yBootstrap(
    "web-nextjs-saas-client", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=client_attrs,
)

# ── API routes bootstrap ───────────────────────────────────────────────────────
api_attrs = {
    "telemetry.sdk.name":     "opentelemetry-node",
    "telemetry.sdk.language": "javascript",
    "framework":              "nextjs",
    "nextjs.version":         "14.0.4",
    "node.version":           "20.10.0",
}
o11y_api = O11yBootstrap(
    "web-nextjs-api-routes", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=api_attrs,
)

# Views configure histogram bucket boundaries aligned with CWV thresholds
cwv_views = [
    View(instrument_name="webvitals.lcp",
         aggregation=ExplicitBucketHistogramAggregation([200, 500, 1000, 2500, 4000, 10000])),
    View(instrument_name="webvitals.inp",
         aggregation=ExplicitBucketHistogramAggregation([50, 100, 200, 500, 1000])),
    View(instrument_name="webvitals.cls",
         aggregation=ExplicitBucketHistogramAggregation([0.01, 0.05, 0.1, 0.15, 0.25, 0.4])),
    View(instrument_name="webvitals.ttfb",
         aggregation=ExplicitBucketHistogramAggregation([100, 200, 500, 800, 1800, 3000])),
    View(instrument_name="webvitals.fcp",
         aggregation=ExplicitBucketHistogramAggregation([500, 1000, 1800, 3000, 5000])),
]

# ── Metrics ────────────────────────────────────────────────────────────────────
ssr_dur_hist    = o11y_ssr.meter.create_histogram("ssr.render_time_ms",  description="SSR render duration",       unit="ms")
hydration_hist  = o11y_client.meter.create_histogram("client.hydration_ms", description="Client hydration time", unit="ms")
lcp_hist        = o11y_client.meter.create_histogram("webvitals.lcp",    description="Largest Contentful Paint",  unit="ms")
cls_hist        = o11y_client.meter.create_histogram("webvitals.cls",    description="Cumulative Layout Shift")
ttfb_hist       = o11y_client.meter.create_histogram("webvitals.ttfb",   description="Time to First Byte",        unit="ms")
page_views      = o11y_client.meter.create_counter("page.view",          description="Page view count")
api_req_counter = o11y_api.meter.create_counter("api.requests",          description="API route request count")

propagator = TraceContextTextMapPropagator()

def inject_traceparent(span):
    carrier = {}
    ctx = propagate.set_span_in_context(span)
    propagator.inject(carrier, context=ctx)
    return carrier

def extract_context(carrier):
    return propagator.extract(carrier)

print(f"\n[web-nextjs-saas] Sending SSR + client traces to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Services: web-nextjs-saas-ssr | web-nextjs-saas-client | web-nextjs-api-routes\n")

results = []

# ── Scenario 1: SSR page render → client hydration ───────────────────────────
try:
    ttfb_ms = random.uniform(50, 800)
    lcp_ms  = random.uniform(800, 4000)
    cls_val = random.uniform(0.001, 0.35)

    # SSR server span
    with o11y_ssr.tracer.start_as_current_span("next.server.render", kind=SpanKind.SERVER) as ssr_span:
        ssr_span.set_attribute("nextjs.page",                 "/products/[id]")
        ssr_span.set_attribute("nextjs.route_type",           "ssr")
        ssr_span.set_attribute("nextjs.dynamic",              True)
        ssr_span.set_attribute("http.request.method",         "GET")
        ssr_span.set_attribute("http.response.status_code",   200)
        ssr_span.set_attribute("vercel.region",               "iad1")
        ssr_span.set_attribute("service.peer.name",           "web-nextjs-saas-api")
        carrier = inject_traceparent(ssr_span)

        with o11y_ssr.tracer.start_as_current_span("next.getServerSideProps", kind=SpanKind.INTERNAL) as gssp:
            gssp.set_attribute("nextjs.page", "/products/[id]")
            with o11y_ssr.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system.name",   "postgresql")
                db_span.set_attribute("db.query.text",    "SELECT * FROM products WHERE id = $1")
                time.sleep(random.uniform(0.01, 0.04))
            time.sleep(random.uniform(0.02, 0.06))

        render_ms = random.uniform(30, 120)
        time.sleep(render_ms / 1000)
        ssr_dur_hist.record(render_ms, attributes={"nextjs.page": "/products/[id]"})

    # Client hydration span (linked via traceparent from SSR)
    remote_ctx = extract_context(carrier)
    hydration_ms = random.uniform(40, 200)
    with o11y_client.tracer.start_as_current_span(
        "client.hydration", kind=SpanKind.INTERNAL, context=remote_ctx
    ) as hyd_span:
        hyd_span.set_attribute("nextjs.page",       "/products/[id]")
        hyd_span.set_attribute("nextjs.route_type", "ssr")
        hyd_span.set_attribute("browser.name",      "Safari")
        hyd_span.set_attribute("session.id",        uuid.uuid4().hex)
        time.sleep(hydration_ms / 1000)

    page_views.add(1, attributes={"page.route": "/products/[id]"})
    hydration_hist.record(hydration_ms, attributes={"nextjs.page": "/products/[id]"})
    lcp_hist.record(lcp_ms, attributes={"nextjs.page": "/products/[id]"})
    cls_hist.record(cls_val, attributes={"nextjs.page": "/products/[id]"})
    ttfb_hist.record(ttfb_ms, attributes={"nextjs.page": "/products/[id]"})
    o11y_ssr.logger.info("SSR render complete", extra={"page": "/products/[id]", "render_ms": round(render_ms, 2)})
    results.append(("SSR page render: getServerSideProps → DB → HTML → client hydrates", "OK", None))
except Exception as e:
    results.append(("SSR page render: getServerSideProps → DB → HTML → client hydrates", "ERROR", str(e)))

# ── Scenario 2: Server Action (form submit) ───────────────────────────────────
try:
    with o11y_ssr.tracer.start_as_current_span("next.server_action", kind=SpanKind.SERVER) as span:
        span.set_attribute("nextjs.route_type",               "server_action")
        span.set_attribute("nextjs.page",                     "/settings/profile")
        span.set_attribute("http.request.method",             "POST")
        span.set_attribute("http.response.status_code",       200)
        span.set_attribute("vercel.region",                   "iad1")
        with o11y_ssr.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name",   "postgresql")
            db_span.set_attribute("db.query.text",    "UPDATE users SET display_name = $1, avatar_url = $2 WHERE id = $3")
            time.sleep(random.uniform(0.01, 0.04))
        # revalidatePath
        with o11y_ssr.tracer.start_as_current_span("next.cache.revalidate", kind=SpanKind.INTERNAL) as cache_span:
            cache_span.set_attribute("nextjs.revalidate_path", "/settings/profile")
            time.sleep(random.uniform(0.005, 0.015))
    o11y_ssr.logger.info("Server action completed", extra={"action": "updateProfile", "page": "/settings/profile"})
    results.append(("Server Action: form submit → server-side mutation → revalidatePath", "OK", None))
except Exception as e:
    results.append(("Server Action: form submit → server-side mutation → revalidatePath", "ERROR", str(e)))

# ── Scenario 3: API Route — Stripe webhook ────────────────────────────────────
try:
    with o11y_api.tracer.start_as_current_span("next.api_route", kind=SpanKind.SERVER) as span:
        span.set_attribute("nextjs.route_type",               "api")
        span.set_attribute("http.route",                      "/api/webhooks/stripe")
        span.set_attribute("http.request.method",             "POST")
        span.set_attribute("http.response.status_code",       200)
        span.set_attribute("nextjs.dynamic",                  True)
        with o11y_api.tracer.start_as_current_span("stripe.webhook.verify", kind=SpanKind.INTERNAL) as vspan:
            vspan.set_attribute("stripe.event_type", "payment_intent.succeeded")
            time.sleep(random.uniform(0.005, 0.02))
        with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name",   "postgresql")
            db_span.set_attribute("db.query.text",    "UPDATE orders SET status = $1, paid_at = NOW() WHERE stripe_payment_intent = $2")
            time.sleep(random.uniform(0.01, 0.03))
    api_req_counter.add(1, attributes={"http.route": "/api/webhooks/stripe"})
    o11y_api.logger.info("Stripe webhook processed", extra={"event": "payment_intent.succeeded"})
    results.append(("API Route: /api/webhooks/stripe → process payment event → 200", "OK", None))
except Exception as e:
    results.append(("API Route: /api/webhooks/stripe → process payment event → 200", "ERROR", str(e)))

# ── Scenario 4: ISR revalidation ──────────────────────────────────────────────
try:
    with o11y_ssr.tracer.start_as_current_span("next.isr.revalidate", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("nextjs.route_type",         "isr")
        span.set_attribute("nextjs.page",               "/blog/[slug]")
        span.set_attribute("nextjs.revalidate_seconds", 60)
        span.set_attribute("nextjs.dynamic",            False)
        span.set_attribute("vercel.region",             "sfo1")
        with o11y_ssr.tracer.start_as_current_span("next.getServerSideProps", kind=SpanKind.INTERNAL) as gssp:
            gssp.set_attribute("nextjs.page", "/blog/[slug]")
            with o11y_ssr.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system.name",   "postgresql")
                db_span.set_attribute("db.query.text",    "SELECT title, content, updated_at FROM posts WHERE slug = $1")
                time.sleep(random.uniform(0.01, 0.04))
        time.sleep(random.uniform(0.04, 0.12))
    o11y_ssr.logger.info("ISR revalidation complete", extra={"page": "/blog/[slug]", "revalidate_seconds": 60})
    results.append(("Static generation: ISR revalidation → rebuild page → cache bust", "OK", None))
except Exception as e:
    results.append(("Static generation: ISR revalidation → rebuild page → cache bust", "ERROR", str(e)))

# ── Scenario 5: Middleware auth check → redirect → login → redirect back ──────
try:
    # Middleware span — unauthenticated request gets redirected
    with o11y_ssr.tracer.start_as_current_span("next.middleware", kind=SpanKind.SERVER) as mw_span:
        mw_span.set_attribute("nextjs.route_type",            "middleware")
        mw_span.set_attribute("http.route",                   "/dashboard")
        mw_span.set_attribute("http.request.method",          "GET")
        mw_span.set_attribute("http.response.status_code",    307)
        mw_span.set_attribute("middleware.action",            "auth_redirect")
        mw_span.set_attribute("redirect.target",              "/login")
        time.sleep(random.uniform(0.002, 0.01))

    # Login page SSR
    with o11y_ssr.tracer.start_as_current_span("next.server.render", kind=SpanKind.SERVER) as login_span:
        login_span.set_attribute("nextjs.page",               "/login")
        login_span.set_attribute("nextjs.route_type",         "ssr")
        login_span.set_attribute("http.request.method",       "GET")
        login_span.set_attribute("http.response.status_code", 200)
        time.sleep(random.uniform(0.01, 0.04))

    # Login form submit (Server Action)
    with o11y_ssr.tracer.start_as_current_span("next.server_action", kind=SpanKind.SERVER) as login_action:
        login_action.set_attribute("nextjs.route_type",           "server_action")
        login_action.set_attribute("nextjs.page",                 "/login")
        login_action.set_attribute("http.request.method",         "POST")
        login_action.set_attribute("http.response.status_code",   200)
        login_action.set_attribute("auth.provider",               "credentials")
        with o11y_ssr.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name",   "postgresql")
            db_span.set_attribute("db.query.text",    "SELECT id, password_hash FROM users WHERE email = $1")
            time.sleep(random.uniform(0.01, 0.03))
        time.sleep(random.uniform(0.02, 0.06))

    # Redirect back to /dashboard after login
    with o11y_ssr.tracer.start_as_current_span("next.middleware", kind=SpanKind.SERVER) as mw2_span:
        mw2_span.set_attribute("nextjs.route_type",           "middleware")
        mw2_span.set_attribute("http.route",                  "/dashboard")
        mw2_span.set_attribute("http.request.method",         "GET")
        mw2_span.set_attribute("http.response.status_code",   200)
        mw2_span.set_attribute("middleware.action",           "auth_pass")
        time.sleep(random.uniform(0.002, 0.008))

    o11y_ssr.logger.info("Auth middleware flow complete", extra={"flow": "redirect→login→redirect_back"})
    results.append(("Middleware: auth check → redirect /login → login → redirect back", "OK", None))
except Exception as e:
    results.append(("Middleware: auth check → redirect /login → login → redirect back", "ERROR", str(e)))

# ── Scenario 6: Edge runtime geolocation middleware ──────────────────────────
try:
    with o11y_ssr.tracer.start_as_current_span("next.middleware", kind=SpanKind.SERVER) as edge_span:
        edge_span.set_attribute("nextjs.route_type",          "middleware")
        edge_span.set_attribute("http.route",                 "/")
        edge_span.set_attribute("http.request.method",        "GET")
        edge_span.set_attribute("http.response.status_code",  200)
        edge_span.set_attribute("edge.runtime",               True)
        edge_span.set_attribute("vercel.region",              "cdg1")
        edge_span.set_attribute("geo.country",                "FR")
        edge_span.set_attribute("geo.city",                   "Paris")
        edge_span.set_attribute("content.locale",             "fr-FR")
        edge_span.set_attribute("middleware.action",          "geo_redirect")
        time.sleep(random.uniform(0.001, 0.006))

    o11y_ssr.logger.info("Edge geolocation middleware", extra={"country": "FR", "locale": "fr-FR", "region": "cdg1"})
    results.append(("Edge runtime: geolocation middleware → country-specific content", "OK", None))
except Exception as e:
    results.append(("Edge runtime: geolocation middleware → country-specific content", "ERROR", str(e)))

# ── Flush all ─────────────────────────────────────────────────────────────────
o11y_ssr.flush()
o11y_client.flush()
o11y_api.flush()

# ── Summary ───────────────────────────────────────────────────────────────────
ok   = sum(1 for _, s, _ in results if s == "OK")
warn = sum(1 for _, s, _ in results if s == "WARN")
err  = sum(1 for _, s, _ in results if s == "ERROR")

for scenario, status, note in results:
    symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
    note_str = f"  ({note})" if note else ""
    print(f"  {symbol} {scenario}{note_str}")

print(f"\n[web-nextjs-saas] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → web-nextjs-saas-ssr | web-nextjs-saas-client | web-nextjs-api-routes")
print(f"  Metrics: ssr.render_time_ms | client.hydration_ms | webvitals.lcp | page.view")
