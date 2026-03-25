#!/usr/bin/env python3
"""
Smoke test: Web — SvelteKit Blog (server + client)

Simulates both SvelteKit server-side spans (load functions, form actions, hooks,
endpoints) and browser-side client spans (navigation, streaming) for a SvelteKit
blog application. Covers the complete request lifecycle including hooks, auth,
DB queries, and real-time streaming via server-sent events.

Run:
    cd smoke-tests && python3 75-web-svelte/smoke.py
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

# ── SvelteKit server bootstrap ─────────────────────────────────────────────────
server_attrs = {
    "telemetry.sdk.name":     "opentelemetry-node",
    "telemetry.sdk.language": "javascript",
    "framework":              "sveltekit",
    "svelte.version":         "4.2.8",
    "node.version":           "20.10.0",
    "sveltekit.adapter":      "node",
}
o11y_server = O11yBootstrap(
    "web-sveltekit-blog-server", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=server_attrs,
)

# ── Browser (client-side) bootstrap ───────────────────────────────────────────
browser_attrs = {
    "browser.name":           "Chrome",
    "browser.version":        "120.0",
    "browser.platform":       "MacIntel",
    "browser.mobile":         False,
    "telemetry.sdk.name":     "opentelemetry-js-web",
    "telemetry.sdk.language": "javascript",
}
o11y_client = O11yBootstrap(
    "web-sveltekit-blog-client", ENDPOINT, API_KEY, ENV,
    extra_resource_attrs=browser_attrs,
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
lcp_hist       = o11y_client.meter.create_histogram("webvitals.lcp",       description="Largest Contentful Paint",  unit="ms")
inp_hist       = o11y_client.meter.create_histogram("webvitals.inp",       description="Interaction to Next Paint", unit="ms")
cls_hist       = o11y_client.meter.create_histogram("webvitals.cls",       description="Cumulative Layout Shift")
ttfb_hist      = o11y_client.meter.create_histogram("webvitals.ttfb",      description="Time to First Byte",        unit="ms")
page_views     = o11y_client.meter.create_counter("page.view",             description="Page view count")
load_dur_hist  = o11y_server.meter.create_histogram("sveltekit.load_ms",   description="SvelteKit load function duration", unit="ms")
sse_counter    = o11y_client.meter.create_counter("sveltekit.sse.messages", description="SSE messages received")

propagator = TraceContextTextMapPropagator()

def inject_traceparent(span):
    carrier = {}
    ctx = propagate.set_span_in_context(span)
    propagator.inject(carrier, context=ctx)
    return carrier

def extract_context(carrier):
    return propagator.extract(carrier)

def session_attrs(route_id):
    return {
        "session.id":           uuid.uuid4().hex,
        "user.id":              f"usr_{uuid.uuid4().hex[:8]}",
        "sveltekit.route.id":   route_id,
    }

print(f"\n[web-sveltekit-blog] Sending server + client traces to {ENDPOINT.split('@')[-1].split('/')[0]}...")
print("  Services: web-sveltekit-blog-server (SvelteKit) + web-sveltekit-blog-client (browser)\n")

results = []

# ── Scenario 1: SvelteKit load function ───────────────────────────────────────
try:
    ttfb_ms = random.uniform(50, 800)
    lcp_ms  = random.uniform(800, 4000)
    cls_val = random.uniform(0.001, 0.35)
    slug    = f"post-{uuid.uuid4().hex[:6]}"

    with o11y_server.tracer.start_as_current_span("sveltekit.load", kind=SpanKind.SERVER) as load_span:
        attrs = session_attrs("/blog/[slug]")
        load_span.set_attributes(attrs)
        load_span.set_attribute("sveltekit.load.type",   "server")
        load_span.set_attribute("sveltekit.page.status", 200)
        load_span.set_attribute("http.request.method",   "GET")
        load_span.set_attribute("http.route",            f"/blog/{slug}")
        carrier = inject_traceparent(load_span)

        with o11y_server.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name",   "postgresql")
            db_span.set_attribute("db.query.text",    "SELECT id, title, content, published_at FROM posts WHERE slug = $1 AND published = TRUE")
            time.sleep(random.uniform(0.01, 0.04))

        load_ms = random.uniform(20, 80)
        time.sleep(load_ms / 1000)
        load_dur_hist.record(load_ms, attributes={"sveltekit.route.id": "/blog/[slug]"})

    # Client receives PageData and renders
    remote_ctx = extract_context(carrier)
    with o11y_client.tracer.start_as_current_span(
        "sveltekit.navigate", kind=SpanKind.INTERNAL, context=remote_ctx
    ) as nav_span:
        nav_span.set_attribute("sveltekit.route.id",   "/blog/[slug]")
        nav_span.set_attribute("sveltekit.page.status", 200)
        nav_span.set_attribute("sveltekit.streaming",  False)
        nav_span.set_attribute("browser.name",         "Chrome")
        nav_span.set_attribute("webvitals.lcp_ms",     round(lcp_ms, 2))
        nav_span.set_attribute("webvitals.ttfb_ms",    round(ttfb_ms, 2))
        nav_span.set_attribute("webvitals.cls_score",  round(cls_val, 4))
        time.sleep(random.uniform(0.02, 0.06))

    page_views.add(1, attributes={"page.route": "/blog/[slug]"})
    lcp_hist.record(lcp_ms,   attributes={"page.route": "/blog/[slug]"})
    cls_hist.record(cls_val,  attributes={"page.route": "/blog/[slug]"})
    ttfb_hist.record(ttfb_ms, attributes={"page.route": "/blog/[slug]"})
    o11y_server.logger.info("Load function complete", extra={"route": "/blog/[slug]", "slug": slug, "load_ms": round(load_ms, 2)})
    results.append(("SvelteKit load: +page.server.js load → DB fetch → PageData returned", "OK", None))
except Exception as e:
    results.append(("SvelteKit load: +page.server.js load → DB fetch → PageData returned", "ERROR", str(e)))

# ── Scenario 2: Form action — create blog post ─────────────────────────────────
try:
    with o11y_server.tracer.start_as_current_span("sveltekit.action", kind=SpanKind.SERVER) as action_span:
        attrs = session_attrs("/blog/new")
        action_span.set_attributes(attrs)
        action_span.set_attribute("sveltekit.action.name",        "createPost")
        action_span.set_attribute("sveltekit.page.status",        303)
        action_span.set_attribute("http.request.method",          "POST")
        action_span.set_attribute("http.route",                   "/blog/new")

        # Validation
        with o11y_server.tracer.start_as_current_span("form.validate", kind=SpanKind.INTERNAL) as val_span:
            val_span.set_attribute("form.fields",       "title,content,tags")
            val_span.set_attribute("form.valid",        True)
            time.sleep(random.uniform(0.002, 0.008))

        # Insert
        with o11y_server.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name",   "postgresql")
            db_span.set_attribute("db.query.text",    "INSERT INTO posts (author_id, title, slug, content, tags) VALUES ($1, $2, $3, $4, $5) RETURNING id, slug")
            time.sleep(random.uniform(0.01, 0.04))

        # Redirect
        with o11y_server.tracer.start_as_current_span("sveltekit.redirect", kind=SpanKind.INTERNAL) as redir_span:
            redir_span.set_attribute("http.response.status_code", 303)
            redir_span.set_attribute("redirect.target",           "/blog/new-post-slug")
            time.sleep(random.uniform(0.001, 0.005))

    o11y_server.logger.info("Blog post created", extra={"action": "createPost", "route": "/blog/new"})
    results.append(("Form action: POST /blog/new → validate → insert → redirect", "OK", None))
except Exception as e:
    results.append(("Form action: POST /blog/new → validate → insert → redirect", "ERROR", str(e)))

# ── Scenario 3: SvelteKit hooks — auth check → locals.user ────────────────────
try:
    with o11y_server.tracer.start_as_current_span("sveltekit.hook.handle", kind=SpanKind.SERVER) as hook_span:
        attrs = session_attrs("/admin/posts")
        hook_span.set_attributes(attrs)
        hook_span.set_attribute("hook.name",            "handle")
        hook_span.set_attribute("http.request.method",  "GET")
        hook_span.set_attribute("http.route",           "/admin/posts")

        # Auth check from session cookie
        with o11y_server.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name",   "postgresql")
            db_span.set_attribute("db.query.text",    "SELECT id, role FROM users WHERE session_token = $1 AND expires_at > NOW()")
            time.sleep(random.uniform(0.005, 0.02))

        hook_span.set_attribute("locals.user.set",    True)
        hook_span.set_attribute("auth.authenticated", True)

        # Resolve continues to load function
        with o11y_server.tracer.start_as_current_span("sveltekit.load", kind=SpanKind.INTERNAL) as load_span:
            load_span.set_attribute("sveltekit.route.id",    "/admin/posts")
            load_span.set_attribute("sveltekit.load.type",   "server")
            load_span.set_attribute("sveltekit.page.status", 200)
            with o11y_server.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db2:
                db2.set_attribute("db.system.name",   "postgresql")
                db2.set_attribute("db.query.text",    "SELECT id, title, status, created_at FROM posts ORDER BY created_at DESC LIMIT 20")
                time.sleep(random.uniform(0.01, 0.03))

    o11y_server.logger.info("Hook auth check passed", extra={"route": "/admin/posts", "hook": "handle"})
    results.append(("SvelteKit hooks: handle() → auth check → locals.user set", "OK", None))
except Exception as e:
    results.append(("SvelteKit hooks: handle() → auth check → locals.user set", "ERROR", str(e)))

# ── Scenario 4: Client-side navigation with goto() ────────────────────────────
try:
    inp_ms = random.uniform(10, 500)
    with o11y_client.tracer.start_as_current_span("sveltekit.navigate", kind=SpanKind.INTERNAL) as nav_span:
        attrs = session_attrs("/blog")
        nav_span.set_attributes(attrs)
        nav_span.set_attribute("sveltekit.page.status",   200)
        nav_span.set_attribute("sveltekit.navigate.type", "goto")
        nav_span.set_attribute("sveltekit.streaming",     False)
        nav_span.set_attribute("page.url",                "https://blog.example.com/blog")
        nav_span.set_attribute("webvitals.inp_ms",        round(inp_ms, 2))

        # Invalidate and refetch load data
        carrier = inject_traceparent(nav_span)
        with o11y_client.tracer.start_as_current_span("fetch.GET /blog", kind=SpanKind.CLIENT) as fetch_span:
            fetch_span.set_attribute("url.full",                  "https://blog.example.com/blog")
            fetch_span.set_attribute("http.request.method",       "GET")
            fetch_span.set_attribute("http.response.status_code", 200)
            fetch_span.set_attribute("service.peer.name",         "web-sveltekit-blog-server")
            carrier2 = inject_traceparent(fetch_span)
            time.sleep(random.uniform(0.04, 0.12))

        # Server load for refreshed data
        remote_ctx = extract_context(carrier2)
        with o11y_server.tracer.start_as_current_span(
            "sveltekit.load", kind=SpanKind.SERVER, context=remote_ctx
        ) as load_span:
            load_span.set_attribute("sveltekit.route.id",    "/blog")
            load_span.set_attribute("sveltekit.load.type",   "universal")
            load_span.set_attribute("sveltekit.page.status", 200)
            with o11y_server.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
                db_span.set_attribute("db.system.name",   "postgresql")
                db_span.set_attribute("db.query.text",    "SELECT id, title, slug, excerpt, published_at FROM posts WHERE published = TRUE ORDER BY published_at DESC LIMIT 10")
                time.sleep(random.uniform(0.01, 0.04))

    page_views.add(1, attributes={"page.route": "/blog"})
    inp_hist.record(inp_ms, attributes={"page.route": "/blog"})
    o11y_client.logger.info("Client navigation complete", extra={"route": "/blog", "type": "goto"})
    results.append(("Client navigation: goto() → load invalidated → data refreshed", "OK", None))
except Exception as e:
    results.append(("Client navigation: goto() → load invalidated → data refreshed", "ERROR", str(e)))

# ── Scenario 5: API endpoint — RSS feed ───────────────────────────────────────
try:
    with o11y_server.tracer.start_as_current_span("sveltekit.endpoint", kind=SpanKind.SERVER) as ep_span:
        attrs = session_attrs("/api/rss")
        ep_span.set_attributes(attrs)
        ep_span.set_attribute("http.route",              "/api/rss")
        ep_span.set_attribute("http.request.method",     "GET")
        ep_span.set_attribute("http.response.status_code", 200)
        ep_span.set_attribute("sveltekit.page.status",   200)
        ep_span.set_attribute("response.content_type",   "application/xml")
        ep_span.set_attribute("sveltekit.streaming",     False)

        with o11y_server.tracer.start_as_current_span("db.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name",   "postgresql")
            db_span.set_attribute("db.query.text",    "SELECT title, slug, excerpt, published_at FROM posts WHERE published = TRUE ORDER BY published_at DESC LIMIT 20")
            time.sleep(random.uniform(0.01, 0.04))

        with o11y_server.tracer.start_as_current_span("rss.generate", kind=SpanKind.INTERNAL) as rss_span:
            rss_span.set_attribute("rss.item_count", 20)
            time.sleep(random.uniform(0.005, 0.015))

    o11y_server.logger.info("RSS feed generated", extra={"route": "/api/rss", "content_type": "application/xml"})
    results.append(("Endpoint: GET /api/rss → generate feed → Content-Type: application/xml", "OK", None))
except Exception as e:
    results.append(("Endpoint: GET /api/rss → generate feed → Content-Type: application/xml", "ERROR", str(e)))

# ── Scenario 6: Server-sent events streaming ──────────────────────────────────
try:
    with o11y_server.tracer.start_as_current_span("sveltekit.stream", kind=SpanKind.SERVER) as stream_span:
        attrs = session_attrs("/blog/[slug]")
        stream_span.set_attributes(attrs)
        stream_span.set_attribute("http.route",                   "/api/comments/stream")
        stream_span.set_attribute("http.request.method",          "GET")
        stream_span.set_attribute("http.response.status_code",    200)
        stream_span.set_attribute("sveltekit.streaming",          True)
        stream_span.set_attribute("response.content_type",        "text/event-stream")
        carrier = inject_traceparent(stream_span)

        # Emit 3 SSE events
        for i in range(3):
            with o11y_server.tracer.start_as_current_span("sse.event", kind=SpanKind.INTERNAL) as sse_span:
                sse_span.set_attribute("sse.event_type",    "comment.new")
                sse_span.set_attribute("sse.sequence",      i + 1)
                time.sleep(random.uniform(0.02, 0.06))

    # Client receives SSE events
    remote_ctx = extract_context(carrier)
    with o11y_client.tracer.start_as_current_span(
        "sveltekit.navigate", kind=SpanKind.INTERNAL, context=remote_ctx
    ) as client_stream_span:
        client_stream_span.set_attribute("sveltekit.route.id",  "/blog/[slug]")
        client_stream_span.set_attribute("sveltekit.streaming", True)
        client_stream_span.set_attribute("sse.event_count",     3)
        time.sleep(random.uniform(0.01, 0.04))

    sse_counter.add(3, attributes={"sse.event_type": "comment.new"})
    o11y_server.logger.info("SSE stream complete", extra={"events": 3, "route": "/api/comments/stream"})
    results.append(("Streaming: server-sent events → real-time comment feed → client update", "OK", None))
except Exception as e:
    results.append(("Streaming: server-sent events → real-time comment feed → client update", "ERROR", str(e)))

# ── Flush all ─────────────────────────────────────────────────────────────────
o11y_server.flush()
o11y_client.flush()

# ── Summary ───────────────────────────────────────────────────────────────────
ok   = sum(1 for _, s, _ in results if s == "OK")
warn = sum(1 for _, s, _ in results if s == "WARN")
err  = sum(1 for _, s, _ in results if s == "ERROR")

for scenario, status, note in results:
    symbol = "✅" if status == "OK" else ("⚠️ " if status == "WARN" else "❌")
    note_str = f"  ({note})" if note else ""
    print(f"  {symbol} {scenario}{note_str}")

print(f"\n[web-sveltekit-blog] Done. {ok} OK | {warn} WARN | {err} ERROR")
print(f"  Kibana → APM → web-sveltekit-blog-server | web-sveltekit-blog-client")
print(f"  Metrics: webvitals.lcp | webvitals.inp | webvitals.cls | page.view | sveltekit.load_ms | sveltekit.sse.messages")
