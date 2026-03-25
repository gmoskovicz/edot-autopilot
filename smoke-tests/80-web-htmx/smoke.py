#!/usr/bin/env python3
"""
Smoke test: HTMX + Flask CRM — server-rendered HTML fragments.

Services modeled:
  web-htmx-crm → web-htmx-db (PostgreSQL calls)

Note: HTMX is a client-side library. Spans come from the server (Flask).
HTMX request patterns: hx-get, hx-post, hx-trigger, hx-swap, hx-boost, hx-ws.

Scenarios:
  1. hx-get lazy load: partial HTML fragment → DB query → return <tr> HTML
  2. hx-post inline form submit: contact form → validate → INSERT → confirmation fragment
  3. hx-trigger polling: every 2s poll /api/queue-status → return badge HTML
  4. hx-ws: WebSocket upgrade → server-sent events → push live updates
  5. hx-boost: progressive enhancement on <a> → full page fetch → swap <body>
  6. Out-of-band swap: main response + OOB toast notification fragment

Run:
    cd smoke-tests && python3 80-web-htmx/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
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
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.metrics import Observation

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

propagator = TraceContextTextMapPropagator()

HTMX_ATTRS = {
    "framework":              "htmx",
    "htmx.version":           "1.9.10",
    "python.version":         "3.11.6",
    "backend.framework":      "flask",
    "telemetry.sdk.name":     "opentelemetry-python",
    "telemetry.sdk.language": "python",
}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
crm    = O11yBootstrap("web-htmx-crm", ENDPOINT, API_KEY, ENV, extra_resource_attrs=HTMX_ATTRS)
db_svc = O11yBootstrap("web-htmx-db",  ENDPOINT, API_KEY, ENV, extra_resource_attrs=HTMX_ATTRS)

# ── Metrics instruments ───────────────────────────────────────────────────────
req_total       = crm.meter.create_counter("htmx.requests_total",       description="Total HTMX requests by trigger type")
fragment_render = crm.meter.create_histogram("htmx.fragment_render_ms", description="HTML fragment render latency", unit="ms")

def _poll_subscriptions_cb(options):
    yield Observation(random.randint(0, 80), {"endpoint": "/api/queue-status"})

crm.meter.create_observable_gauge(
    "htmx.poll.active_subscriptions", [_poll_subscriptions_cb],
    description="Active HTMX polling subscriptions")

SVC = "web-htmx-crm"
print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — hx-get lazy load: partial HTML fragment → DB query → return <tr>
# ─────────────────────────────────────────────────────────────────────────────
try:
    contact_id = random.randint(1, 9999)
    t0 = time.time()

    with crm.tracer.start_as_current_span(
        "htmx.hx-get.fragment", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("htmx.trigger", "hx-get")
        span.set_attribute("htmx.target", "#contacts-table tbody")
        span.set_attribute("htmx.swap", "beforeend")
        span.set_attribute("htmx.request.partial", True)
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("http.route", "/crm/contacts/rows")
        span.set_attribute("http.request_header.hx_request", "true")
        span.set_attribute("http.request_header.hx_trigger", "contacts-table")

        with db_svc.tracer.start_as_current_span(
            "flask.db.query", kind=SpanKind.CLIENT
        ) as db_span:
            db_span.set_attribute("db.system.name", "postgresql")
            db_span.set_attribute("db.operation.name", "SELECT")
            db_span.set_attribute("db.query.text", "SELECT contacts.id, contacts.name, contacts.email, contacts.status FROM contacts ORDER BY updated_at DESC LIMIT 20")
            db_span.set_attribute("db.collection.name", "contacts")
            db_span.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.01, 0.04))

        fragment_bytes = random.randint(512, 4096)
        span.set_attribute("response.content_type", "text/html")
        span.set_attribute("response.fragment_size_bytes", fragment_bytes)
        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"htmx.trigger": "hx-get", "htmx.partial": "true"})
    fragment_render.record(dur_ms, {"htmx.trigger": "hx-get"})
    crm.logger.info("hx-get fragment rendered", extra={"fragment_bytes": fragment_bytes, "duration_ms": round(dur_ms, 2)})
    print("  ✅ Scenario 1 — hx-get lazy load: partial HTML fragment → DB query → <tr> rows")
except Exception as exc:
    print(f"  ❌ Scenario 1 — hx-get lazy load: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — hx-post inline form submit: contact form → validate → INSERT → confirmation
# ─────────────────────────────────────────────────────────────────────────────
try:
    new_contact_id = random.randint(10000, 99999)
    form_valid = True
    t0 = time.time()

    with crm.tracer.start_as_current_span(
        "htmx.hx-post.form", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("htmx.trigger", "hx-post")
        span.set_attribute("htmx.target", "#contact-form-container")
        span.set_attribute("htmx.swap", "outerHTML")
        span.set_attribute("htmx.request.partial", True)
        span.set_attribute("http.request.method", "POST")
        span.set_attribute("http.route", "/crm/contacts")
        span.set_attribute("form.name", "new-contact-form")

        with crm.tracer.start_as_current_span(
            "flask.form_validation", kind=SpanKind.INTERNAL
        ) as val_span:
            val_span.set_attribute("validation.form", "ContactForm")
            val_span.set_attribute("validation.passed", form_valid)
            time.sleep(random.uniform(0.001, 0.005))

        if form_valid:
            with db_svc.tracer.start_as_current_span(
                "flask.db.query", kind=SpanKind.CLIENT
            ) as db_span:
                db_span.set_attribute("db.system.name", "postgresql")
                db_span.set_attribute("db.operation.name", "INSERT")
                db_span.set_attribute("db.query.text", "INSERT INTO contacts (name, email, phone, status, created_at) VALUES ($1, $2, $3, 'new', NOW()) RETURNING id")
                db_span.set_attribute("db.collection.name", "contacts")
                db_span.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.01, 0.04))

        fragment_bytes = random.randint(128, 512)
        span.set_attribute("response.content_type", "text/html")
        span.set_attribute("response.fragment_size_bytes", fragment_bytes)
        span.set_attribute("http.response.status_code", 200)
        span.set_attribute("contact.id", new_contact_id)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"htmx.trigger": "hx-post", "htmx.partial": "true"})
    fragment_render.record(dur_ms, {"htmx.trigger": "hx-post"})
    crm.logger.info("Contact form submitted and confirmed", extra={"contact_id": new_contact_id})
    print("  ✅ Scenario 2 — hx-post form submit → validate → INSERT → confirmation HTML fragment")
except Exception as exc:
    print(f"  ❌ Scenario 2 — hx-post form: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — hx-trigger polling: every 2s poll /api/queue-status → badge HTML
# ─────────────────────────────────────────────────────────────────────────────
try:
    poll_count = random.randint(3, 7)

    for i in range(poll_count):
        queue_depth = random.randint(0, 50)
        t0 = time.time()

        with crm.tracer.start_as_current_span(
            "htmx.poll.queue-status", kind=SpanKind.SERVER
        ) as span:
            span.set_attribute("htmx.trigger", "hx-trigger")
            span.set_attribute("htmx.trigger_spec", "every 2s")
            span.set_attribute("htmx.target", "#queue-badge")
            span.set_attribute("htmx.swap", "innerHTML")
            span.set_attribute("htmx.request.partial", True)
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("http.route", "/api/queue-status")
            span.set_attribute("poll.interval_ms", 2000)
            span.set_attribute("poll.iteration", i + 1)

            with db_svc.tracer.start_as_current_span(
                "flask.db.query", kind=SpanKind.CLIENT
            ) as db_span:
                db_span.set_attribute("db.system.name", "postgresql")
                db_span.set_attribute("db.operation.name", "SELECT")
                db_span.set_attribute("db.query.text", "SELECT COUNT(*) FROM task_queue WHERE status = 'pending'")
                db_span.set_attribute("db.collection.name", "task_queue")
                db_span.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.003, 0.012))

            fragment_bytes = random.randint(32, 128)
            span.set_attribute("response.content_type", "text/html")
            span.set_attribute("response.fragment_size_bytes", fragment_bytes)
            span.set_attribute("queue.depth", queue_depth)
            span.set_attribute("http.response.status_code", 200)

        dur_ms = (time.time() - t0) * 1000
        req_total.add(1, {"htmx.trigger": "hx-trigger-poll", "htmx.partial": "true"})
        fragment_render.record(dur_ms, {"htmx.trigger": "hx-trigger-poll"})

    crm.logger.info("Queue-status polling completed", extra={"poll_count": poll_count})
    print(f"  ✅ Scenario 3 — hx-trigger polling ({poll_count} polls) → badge HTML fragment")
except Exception as exc:
    print(f"  ❌ Scenario 3 — hx-trigger polling: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — hx-ws: WebSocket upgrade → server-sent events → push live updates
# ─────────────────────────────────────────────────────────────────────────────
try:
    ws_id      = f"ws_{uuid.uuid4().hex[:6]}"
    n_events   = random.randint(3, 8)

    with crm.tracer.start_as_current_span(
        "htmx.websocket.connect", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("htmx.trigger", "hx-ws")
        span.set_attribute("htmx.target", "#live-feed")
        span.set_attribute("htmx.swap", "beforeend")
        span.set_attribute("websocket.id", ws_id)
        span.set_attribute("websocket.url", "/ws/live-updates")
        span.set_attribute("messaging.system", "websocket")

        with crm.tracer.start_as_current_span(
            "websocket.upgrade", kind=SpanKind.INTERNAL
        ) as up_span:
            up_span.set_attribute("websocket.id", ws_id)
            up_span.set_attribute("http.response.status_code", 101)
            time.sleep(random.uniform(0.002, 0.008))

        for i in range(n_events):
            with crm.tracer.start_as_current_span(
                "websocket.send_html_fragment", kind=SpanKind.INTERNAL
            ) as ev_span:
                ev_span.set_attribute("websocket.id", ws_id)
                ev_span.set_attribute("websocket.event_index", i)
                ev_span.set_attribute("htmx.swap", "beforeend")
                ev_span.set_attribute("response.content_type", "text/html")
                ev_span.set_attribute("response.fragment_size_bytes", random.randint(64, 256))
                time.sleep(random.uniform(0.005, 0.02))

        span.set_attribute("websocket.events_sent", n_events)

    crm.logger.info("hx-ws live-updates session completed", extra={"ws_id": ws_id, "events_sent": n_events})
    print(f"  ✅ Scenario 4 — hx-ws WebSocket upgrade → {n_events} server-sent HTML fragments → live updates")
except Exception as exc:
    print(f"  ❌ Scenario 4 — hx-ws WebSocket: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 — hx-boost: progressive enhancement → full page fetch → swap <body>
# ─────────────────────────────────────────────────────────────────────────────
try:
    target_path = "/crm/contacts/detail/42"
    t0 = time.time()

    with crm.tracer.start_as_current_span(
        "htmx.hx-boost.navigate", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("htmx.trigger", "hx-boost")
        span.set_attribute("htmx.target", "body")
        span.set_attribute("htmx.swap", "outerHTML")
        span.set_attribute("htmx.request.boosted", True)
        span.set_attribute("htmx.request.partial", False)
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("http.route", target_path)
        span.set_attribute("http.request_header.hx_boosted", "true")

        with db_svc.tracer.start_as_current_span(
            "flask.db.query", kind=SpanKind.CLIENT
        ) as db_span:
            db_span.set_attribute("db.system.name", "postgresql")
            db_span.set_attribute("db.operation.name", "SELECT")
            db_span.set_attribute("db.query.text", "SELECT contacts.*, notes.*, tasks.* FROM contacts LEFT JOIN notes ON notes.contact_id = contacts.id LEFT JOIN tasks ON tasks.contact_id = contacts.id WHERE contacts.id = $1")
            db_span.set_attribute("db.collection.name", "contacts")
            db_span.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.015, 0.06))

        page_bytes = random.randint(8192, 32768)
        span.set_attribute("response.content_type", "text/html")
        span.set_attribute("response.fragment_size_bytes", page_bytes)
        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"htmx.trigger": "hx-boost", "htmx.partial": "false"})
    fragment_render.record(dur_ms, {"htmx.trigger": "hx-boost"})
    crm.logger.info("hx-boost full page rendered", extra={"path": target_path, "page_bytes": page_bytes})
    print("  ✅ Scenario 5 — hx-boost progressive enhancement → full page fetch → swap <body>")
except Exception as exc:
    print(f"  ❌ Scenario 5 — hx-boost: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 — Out-of-band swap: main response + OOB toast notification
# ─────────────────────────────────────────────────────────────────────────────
try:
    action_id = uuid.uuid4().hex[:8]
    t0 = time.time()

    with crm.tracer.start_as_current_span(
        "htmx.hx-post.form", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("htmx.trigger", "hx-post")
        span.set_attribute("htmx.target", "#deal-list")
        span.set_attribute("htmx.swap", "outerHTML")
        span.set_attribute("htmx.request.partial", True)
        span.set_attribute("http.request.method", "POST")
        span.set_attribute("http.route", "/crm/deals")

        with db_svc.tracer.start_as_current_span(
            "flask.db.query", kind=SpanKind.CLIENT
        ) as db_span:
            db_span.set_attribute("db.system.name", "postgresql")
            db_span.set_attribute("db.operation.name", "INSERT")
            db_span.set_attribute("db.query.text", "INSERT INTO deals (title, value, stage, contact_id, created_at) VALUES ($1, $2, $3, $4, NOW()) RETURNING id")
            db_span.set_attribute("db.collection.name", "deals")
            db_span.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.01, 0.04))

        # Main fragment (updated deal list)
        with crm.tracer.start_as_current_span(
            "flask.render_template.deal_list", kind=SpanKind.INTERNAL
        ) as main_span:
            main_span.set_attribute("template.name", "_deal_list.html")
            main_span.set_attribute("response.fragment_size_bytes", random.randint(1024, 4096))
            time.sleep(random.uniform(0.003, 0.01))

        # OOB toast notification
        with crm.tracer.start_as_current_span(
            "htmx.oob.toast", kind=SpanKind.INTERNAL
        ) as oob_span:
            oob_span.set_attribute("htmx.oob", True)
            oob_span.set_attribute("htmx.oob.target", "#toast-container")
            oob_span.set_attribute("htmx.swap", "beforeend")
            oob_span.set_attribute("toast.message", "Deal created successfully")
            oob_span.set_attribute("toast.type", "success")
            toast_bytes = random.randint(64, 256)
            oob_span.set_attribute("response.fragment_size_bytes", toast_bytes)
            time.sleep(random.uniform(0.001, 0.004))

        span.set_attribute("response.content_type", "text/html")
        span.set_attribute("response.oob_swap", True)
        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"htmx.trigger": "hx-post", "htmx.partial": "true"})
    fragment_render.record(dur_ms, {"htmx.trigger": "hx-post-oob"})
    crm.logger.info("OOB swap: deal list updated + toast notification sent",
                    extra={"action_id": action_id, "oob": True})
    print("  ✅ Scenario 6 — Out-of-band swap: main deal list fragment + OOB toast notification")
except Exception as exc:
    print(f"  ❌ Scenario 6 — OOB swap: {exc}")

# ── Flush all ─────────────────────────────────────────────────────────────────
crm.flush()
db_svc.flush()

print(f"\n[{SVC}] Done. APM → {SVC} | Metrics: htmx.requests_total, htmx.fragment_render_ms")
