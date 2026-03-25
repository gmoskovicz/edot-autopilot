#!/usr/bin/env python3
"""
Smoke test: Web — React SPA (ShopClient)

Simulates browser RUM traces from a React single-page application using the
OpenTelemetry Web SDK pattern, plus server-side spans from an Express API.
Covers page loads, user interactions, fetch calls, Core Web Vitals, and
frontend→backend trace propagation.

Run:
    cd smoke-tests && python3 71-web-react-spa/smoke.py
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

# ── Browser (client-side RUM) bootstrap ───────────────────────────────────────
browser_attrs = {
    "browser.name":             "Chrome",
    "browser.version":          "120.0",
    "browser.platform":         "Win32",
    "browser.language":         "en-US",
    "browser.mobile":           False,
    "telemetry.sdk.name":       "opentelemetry-js-web",
    "telemetry.sdk.version":    "1.18.0",
    "telemetry.sdk.language":   "javascript",
    "user_agent.original":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
}
o11y_browser = O11yBootstrap(
    "web-react-shop-client", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=browser_attrs,
)

# ── API backend (Express) bootstrap ───────────────────────────────────────────
api_attrs = {
    "telemetry.sdk.name":     "opentelemetry-node",
    "telemetry.sdk.language": "javascript",
    "framework":              "express",
    "node.version":           "20.10.0",
}
o11y_api = O11yBootstrap(
    "web-react-shop-api", ENDPOINT, API_KEY, ENV,
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

# ── Metric instruments (browser) ──────────────────────────────────────────────
lcp_hist       = o11y_browser.meter.create_histogram("webvitals.lcp",        description="Largest Contentful Paint",    unit="ms")
inp_hist       = o11y_browser.meter.create_histogram("webvitals.inp",        description="Interaction to Next Paint",   unit="ms")
cls_hist       = o11y_browser.meter.create_histogram("webvitals.cls",        description="Cumulative Layout Shift")
ttfb_hist      = o11y_browser.meter.create_histogram("webvitals.ttfb",       description="Time to First Byte",          unit="ms")
fcp_hist       = o11y_browser.meter.create_histogram("webvitals.fcp",        description="First Contentful Paint",      unit="ms")
page_views     = o11y_browser.meter.create_counter("page.view",              description="Page view count")
fetch_dur_hist = o11y_browser.meter.create_histogram("fetch.duration_ms",    description="Fetch call duration",         unit="ms")

propagator = TraceContextTextMapPropagator()

def inject_traceparent(span):
    """Inject W3C traceparent from a browser span into a carrier dict."""
    carrier = {}
    ctx = propagate.set_span_in_context(span)
    propagator.inject(carrier, context=ctx)
    return carrier

def extract_context(carrier):
    """Extract trace context from a W3C traceparent carrier."""
    return propagator.extract(carrier)

def session_attrs(page_url, referrer=None):
    attrs = {
        "session.id":    uuid.uuid4().hex,
        "user.id":       f"usr_{uuid.uuid4().hex[:8]}",
        "page.url":      page_url,
    }
    if referrer:
        attrs["page.referrer"] = referrer
    return attrs

print(f"\n[web-react-shop] Sending browser RUM + API traces to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Services: web-react-shop-client (browser) + web-react-shop-api (Express)\n")

results = []

# ── Scenario 1: Initial page load with LCP ────────────────────────────────────
try:
    lcp_ms  = random.uniform(800, 4000)
    fcp_ms  = lcp_ms * random.uniform(0.5, 0.8)
    ttfb_ms = random.uniform(50, 800)
    cls_val = random.uniform(0.001, 0.35)

    with o11y_browser.tracer.start_as_current_span("documentLoad", kind=SpanKind.INTERNAL) as span:
        attrs = session_attrs("https://shop.example.com/products")
        span.set_attributes(attrs)
        span.set_attribute("url.full",              "https://shop.example.com/products")
        span.set_attribute("http.request.method",   "GET")
        span.set_attribute("http.response.status_code", 200)
        span.set_attribute("webvitals.lcp_ms",      round(lcp_ms, 2))
        span.set_attribute("webvitals.fcp_ms",      round(fcp_ms, 2))
        span.set_attribute("webvitals.ttfb_ms",     round(ttfb_ms, 2))
        span.set_attribute("webvitals.cls_score",   round(cls_val, 4))
        time.sleep(ttfb_ms / 1000)

        with o11y_browser.tracer.start_as_current_span("react.render", kind=SpanKind.INTERNAL) as hydration:
            hydration.set_attribute("react.component", "App")
            hydration.set_attribute("react.hydration", True)
            time.sleep(random.uniform(0.05, 0.15))

    page_views.add(1, attributes={"page.route": "/products"})
    lcp_hist.record(lcp_ms,    attributes={"page.route": "/products"})
    fcp_hist.record(fcp_ms,    attributes={"page.route": "/products"})
    ttfb_hist.record(ttfb_ms,  attributes={"page.route": "/products"})
    cls_hist.record(cls_val,   attributes={"page.route": "/products"})
    o11y_browser.logger.info("Page load complete", extra={"page.url": "https://shop.example.com/products", "lcp_ms": round(lcp_ms, 2)})
    results.append(("Initial page load: document.load → React hydration → LCP", "OK", None))
except Exception as e:
    results.append(("Initial page load: document.load → React hydration → LCP", "ERROR", str(e)))

# ── Scenario 2: Product search (INP measured) ─────────────────────────────────
try:
    inp_ms = random.uniform(10, 500)
    with o11y_browser.tracer.start_as_current_span("user.interaction.click", kind=SpanKind.INTERNAL) as ui_span:
        s_attrs = session_attrs("https://shop.example.com/products")
        ui_span.set_attributes(s_attrs)
        ui_span.set_attribute("ui.element",          "search-input")
        ui_span.set_attribute("ui.event_type",       "keydown")
        ui_span.set_attribute("webvitals.inp_ms",    round(inp_ms, 2))
        time.sleep(inp_ms / 1000)

        # Debounced fetch after user types
        carrier = inject_traceparent(ui_span)
        fetch_start = time.time()
        with o11y_browser.tracer.start_as_current_span("fetch.GET /api/products", kind=SpanKind.CLIENT) as fetch_span:
            fetch_span.set_attributes(s_attrs)
            fetch_span.set_attribute("url.full",              "https://api.shop.example.com/api/products?q=sneakers")
            fetch_span.set_attribute("http.request.method",   "GET")
            fetch_span.set_attribute("http.response.status_code", 200)
            fetch_span.set_attribute("service.peer.name",    "web-react-shop-api")
            carrier2 = inject_traceparent(fetch_span)
            time.sleep(random.uniform(0.08, 0.25))
        fetch_ms = (time.time() - fetch_start) * 1000
        fetch_dur_hist.record(fetch_ms, attributes={"http.route": "/api/products", "http.request.method": "GET"})

        # Server-side Express handler (linked via traceparent)
        remote_ctx = extract_context(carrier2)
        with o11y_api.tracer.start_as_current_span(
            "GET /api/products", kind=SpanKind.SERVER, context=remote_ctx
        ) as srv_span:
            srv_span.set_attribute("http.route",                  "/api/products")
            srv_span.set_attribute("http.request.method",         "GET")
            srv_span.set_attribute("http.response.status_code",   200)
            srv_span.set_attribute("framework.name",              "express")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system.name",   "postgresql")
                db_span.set_attribute("db.query.text",    "SELECT id, name, price FROM products WHERE name ILIKE $1 LIMIT 20")
                time.sleep(random.uniform(0.01, 0.04))

    inp_hist.record(inp_ms, attributes={"page.route": "/products"})
    o11y_browser.logger.info("Product search fetch complete", extra={"query": "sneakers", "inp_ms": round(inp_ms, 2)})
    results.append(("Product search: user types → debounced fetch → results rendered (INP)", "OK", None))
except Exception as e:
    results.append(("Product search: user types → debounced fetch → results rendered (INP)", "ERROR", str(e)))

# ── Scenario 3: Add to cart ───────────────────────────────────────────────────
try:
    product_id = f"PROD-{uuid.uuid4().hex[:6].upper()}"
    with o11y_browser.tracer.start_as_current_span("user.interaction.click", kind=SpanKind.INTERNAL) as click_span:
        s_attrs = session_attrs("https://shop.example.com/products")
        click_span.set_attributes(s_attrs)
        click_span.set_attribute("ui.element",   "add-to-cart-button")
        click_span.set_attribute("product.id",   product_id)
        click_span.set_attribute("ui.event_type", "click")
        time.sleep(random.uniform(0.01, 0.03))

        # Optimistic UI update then POST
        fetch_start = time.time()
        with o11y_browser.tracer.start_as_current_span("fetch.POST /api/cart", kind=SpanKind.CLIENT) as fetch_span:
            fetch_span.set_attributes(s_attrs)
            fetch_span.set_attribute("url.full",                  "https://api.shop.example.com/api/cart")
            fetch_span.set_attribute("http.request.method",       "POST")
            fetch_span.set_attribute("http.response.status_code", 201)
            fetch_span.set_attribute("service.peer.name",         "web-react-shop-api")
            carrier2 = inject_traceparent(fetch_span)
            time.sleep(random.uniform(0.06, 0.18))
        fetch_ms = (time.time() - fetch_start) * 1000
        fetch_dur_hist.record(fetch_ms, attributes={"http.route": "/api/cart", "http.request.method": "POST"})

        # Express handler
        remote_ctx = extract_context(carrier2)
        with o11y_api.tracer.start_as_current_span(
            "POST /api/cart", kind=SpanKind.SERVER, context=remote_ctx
        ) as srv_span:
            srv_span.set_attribute("http.route",                  "/api/cart")
            srv_span.set_attribute("http.request.method",         "POST")
            srv_span.set_attribute("http.response.status_code",   201)
            srv_span.set_attribute("framework.name",              "express")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system.name",   "postgresql")
                db_span.set_attribute("db.query.text",    "INSERT INTO cart_items (session_id, product_id, qty) VALUES ($1, $2, $3)")
                time.sleep(random.uniform(0.01, 0.03))

    o11y_browser.logger.info("Add to cart success", extra={"product.id": product_id})
    results.append(("Add to cart: click → optimistic update → POST → toast", "OK", None))
except Exception as e:
    results.append(("Add to cart: click → optimistic update → POST → toast", "ERROR", str(e)))

# ── Scenario 4: SPA route change ─────────────────────────────────────────────
try:
    routes = [
        ("/products",     "https://shop.example.com/products"),
        ("/product/123",  "https://shop.example.com/product/123"),
        ("/cart",         "https://shop.example.com/cart"),
    ]
    for i, (route, url) in enumerate(routes):
        referrer = routes[i - 1][1] if i > 0 else None
        with o11y_browser.tracer.start_as_current_span("react.render", kind=SpanKind.INTERNAL) as span:
            span.set_attributes(session_attrs(url, referrer=referrer))
            span.set_attribute("react.component",       route.strip("/").replace("/", ".").capitalize() or "Products")
            span.set_attribute("spa.navigation_type",   "pushState")
            span.set_attribute("page.route",            route)
            time.sleep(random.uniform(0.02, 0.07))
        page_views.add(1, attributes={"page.route": route})

    o11y_browser.logger.info("SPA navigation complete", extra={"flow": "/products → /product/123 → /cart"})
    results.append(("Route change: /products → /product/123 → /cart (SPA, no reload)", "OK", None))
except Exception as e:
    results.append(("Route change: /products → /product/123 → /cart (SPA, no reload)", "ERROR", str(e)))

# ── Scenario 5: Checkout form with validation error then success ───────────────
try:
    with o11y_browser.tracer.start_as_current_span("user.interaction.click", kind=SpanKind.INTERNAL) as span:
        s_attrs = session_attrs("https://shop.example.com/checkout", referrer="https://shop.example.com/cart")
        span.set_attributes(s_attrs)
        span.set_attribute("ui.element",        "checkout-form")
        span.set_attribute("ui.event_type",     "submit")
        span.set_attribute("form.validation",   "failed")
        span.set_attribute("form.error_fields", "card_number,expiry")
        # Simulate validation error — not a fatal error, just a warning
        o11y_browser.logger.warning("Form validation failed", extra={"fields": "card_number,expiry"})
        time.sleep(random.uniform(0.01, 0.04))

    # User fixes and resubmits
    with o11y_browser.tracer.start_as_current_span("user.interaction.click", kind=SpanKind.INTERNAL) as span:
        s_attrs = session_attrs("https://shop.example.com/checkout")
        span.set_attributes(s_attrs)
        span.set_attribute("ui.element",    "checkout-form")
        span.set_attribute("ui.event_type", "submit")
        span.set_attribute("form.valid",    True)

        fetch_start = time.time()
        with o11y_browser.tracer.start_as_current_span("fetch.POST /api/checkout", kind=SpanKind.CLIENT) as fetch_span:
            fetch_span.set_attribute("url.full",                  "https://api.shop.example.com/api/checkout")
            fetch_span.set_attribute("http.request.method",       "POST")
            fetch_span.set_attribute("http.response.status_code", 201)
            fetch_span.set_attribute("service.peer.name",         "web-react-shop-api")
            carrier2 = inject_traceparent(fetch_span)
            time.sleep(random.uniform(0.12, 0.35))
        fetch_ms = (time.time() - fetch_start) * 1000
        fetch_dur_hist.record(fetch_ms, attributes={"http.route": "/api/checkout", "http.request.method": "POST"})

        remote_ctx = extract_context(carrier2)
        with o11y_api.tracer.start_as_current_span(
            "POST /api/checkout", kind=SpanKind.SERVER, context=remote_ctx
        ) as srv_span:
            srv_span.set_attribute("http.route",                  "/api/checkout")
            srv_span.set_attribute("http.request.method",         "POST")
            srv_span.set_attribute("http.response.status_code",   201)
            srv_span.set_attribute("framework.name",              "express")
            with o11y_api.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system.name",   "postgresql")
                db_span.set_attribute("db.query.text",    "INSERT INTO orders (user_id, total_usd, status) VALUES ($1, $2, $3) RETURNING id")
                time.sleep(random.uniform(0.02, 0.06))

    page_views.add(1, attributes={"page.route": "/checkout/success"})
    o11y_browser.logger.info("Checkout submitted successfully", extra={"redirect": "/checkout/success"})
    results.append(("Checkout form: validation errors → fix → submit → redirect", "OK", None))
except Exception as e:
    results.append(("Checkout form: validation errors → fix → submit → redirect", "ERROR", str(e)))

# ── Scenario 6: Lazy component load ──────────────────────────────────────────
try:
    with o11y_browser.tracer.start_as_current_span("component.lazy_load", kind=SpanKind.INTERNAL) as span:
        s_attrs = session_attrs("https://shop.example.com/checkout")
        span.set_attributes(s_attrs)
        span.set_attribute("component.name",    "CheckoutForm")
        span.set_attribute("chunk.name",        "CheckoutForm.chunk.js")
        chunk_ms = random.uniform(80, 400)
        span.set_attribute("chunk.download_ms", round(chunk_ms, 2))
        time.sleep(chunk_ms / 1000)

        with o11y_browser.tracer.start_as_current_span("react.render", kind=SpanKind.INTERNAL) as render_span:
            render_span.set_attribute("react.component", "CheckoutForm")
            render_span.set_attribute("react.lazy",      True)
            time.sleep(random.uniform(0.02, 0.06))

    o11y_browser.logger.info("Lazy component loaded", extra={"component": "CheckoutForm", "chunk_ms": round(chunk_ms, 2)})
    results.append(("Lazy component: import('./CheckoutForm') → chunk download → render", "OK", None))
except Exception as e:
    results.append(("Lazy component: import('./CheckoutForm') → chunk download → render", "ERROR", str(e)))

# ── Flush all ─────────────────────────────────────────────────────────────────
o11y_browser.flush()
o11y_api.flush()

# ── Summary ───────────────────────────────────────────────────────────────────
ok   = sum(1 for _, s, _ in results if s == "OK")
warn = sum(1 for _, s, _ in results if s == "WARN")
err  = sum(1 for _, s, _ in results if s == "ERROR")

for scenario, status, note in results:
    symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
    note_str = f"  ({note})" if note else ""
    print(f"  {symbol} {scenario}{note_str}")

print(f"\n[web-react-shop] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → web-react-shop-client | web-react-shop-api")
print(f"  Metrics: webvitals.lcp | webvitals.inp | webvitals.cls | page.view | fetch.duration_ms")
