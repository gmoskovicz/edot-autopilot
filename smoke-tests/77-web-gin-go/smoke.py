#!/usr/bin/env python3
"""
Smoke test: Gin (Go) — Inventory API with middleware chain, GORM, Redis, goroutine fan-out.

Services modeled:
  web-gin-inventory-api → web-gin-postgres-calls
                        → web-gin-redis-cache

Scenarios:
  1. Middleware chain: CORS → RateLimiter → JWT Auth → handler
  2. Route group /api/v2/inventory → pagination → Redis miss → DB → cache set
  3. Gin validation: ShouldBindJSON → validator.v10 → 422 bad request
  4. Goroutine fan-out: 3 concurrent DB queries → WaitGroup → merge
  5. GORM transaction: BEGIN → insert item → update stock → insert audit_log → COMMIT
  6. Graceful shutdown: SIGTERM → drain → flush OTel → exit

Run:
    cd smoke-tests && python3 77-web-gin-go/smoke.py
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

GIN_ATTRS = {
    "framework":              "gin",
    "gin.version":            "1.9.1",
    "go.version":             "1.21.5",
    "telemetry.sdk.name":     "opentelemetry-go",
    "telemetry.sdk.language": "go",
}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
api      = O11yBootstrap("web-gin-inventory-api",  ENDPOINT, API_KEY, ENV, extra_resource_attrs=GIN_ATTRS)
pg_svc   = O11yBootstrap("web-gin-postgres-calls", ENDPOINT, API_KEY, ENV, extra_resource_attrs=GIN_ATTRS)
redis_svc = O11yBootstrap("web-gin-redis-cache",   ENDPOINT, API_KEY, ENV, extra_resource_attrs=GIN_ATTRS)

# ── Metrics instruments ───────────────────────────────────────────────────────
req_total       = api.meter.create_counter("gin.request",              description="Total Gin HTTP requests")
req_duration    = api.meter.create_histogram("gin.request.duration",   description="Gin request latency", unit="ms")
db_duration     = pg_svc.meter.create_histogram("db.client.operation.duration", description="DB query latency", unit="ms")

def _goroutines_cb(options):
    yield Observation(random.randint(8, 64), {"service": "web-gin-inventory-api"})

api.meter.create_observable_gauge(
    "gin.concurrent_goroutines", [_goroutines_cb],
    description="Active goroutines")

SVC = "web-gin-inventory-api"
print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Middleware chain: CORS → RateLimiter → JWT Auth → handler
# ─────────────────────────────────────────────────────────────────────────────
try:
    item_id = str(uuid.uuid4())
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "gin.handler.GET /api/v2/inventory/:id", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("gin.route", "/api/v2/inventory/:id")
        span.set_attribute("gin.handler_name", "getInventoryItem")
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("http.route", "/api/v2/inventory/:id")
        span.set_attribute("url.path", f"/api/v2/inventory/{item_id}")

        middlewares = [
            ("gin.middleware.CORS",        {"gin.middleware": "CORS",        "cors.origin": "https://shop.example.com"}),
            ("gin.middleware.RateLimiter", {"gin.middleware": "RateLimiter", "rate_limiter.key": "ip:203.0.113.5", "rate_limiter.remaining": random.randint(0, 100)}),
            ("gin.middleware.JWTAuth",     {"gin.middleware": "JWTAuth",     "auth.subject": "user_42", "auth.token_valid": True}),
        ]
        for mw_name, mw_attrs in middlewares:
            with api.tracer.start_as_current_span(mw_name, kind=SpanKind.INTERNAL) as mw_span:
                for k, v in mw_attrs.items():
                    mw_span.set_attribute(k, v)
                time.sleep(random.uniform(0.002, 0.008))

        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "GET", "http.route": "/api/v2/inventory/:id", "http.response.status_code": "200"})
    req_duration.record(dur_ms, {"http.request.method": "GET"})
    api.logger.info("GET /api/v2/inventory/:id handled", extra={"item_id": item_id, "duration_ms": round(dur_ms, 2)})
    print("  ✅ Scenario 1 — Middleware chain CORS → RateLimiter → JWTAuth → handler")
except Exception as exc:
    print(f"  ❌ Scenario 1 — Middleware chain: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — Route group: pagination → Redis cache miss → DB → cache set
# ─────────────────────────────────────────────────────────────────────────────
try:
    page      = random.randint(1, 10)
    page_size = 20
    cache_key = f"inventory:page:{page}:size:{page_size}"
    cache_hit = False  # simulate cache miss
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "gin.handler.GET /api/v2/inventory/items", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("gin.route", "/api/v2/inventory/items")
        span.set_attribute("gin.handler_name", "listInventoryItems")
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("pagination.page", page)
        span.set_attribute("pagination.size", page_size)

        with redis_svc.tracer.start_as_current_span("redis.GET", kind=SpanKind.CLIENT) as r_span:
            r_span.set_attribute("db.system.name", "redis")
            r_span.set_attribute("db.operation.name", "GET")
            r_span.set_attribute("cache.key", cache_key)
            r_span.set_attribute("cache.hit", cache_hit)
            r_span.set_attribute("service.peer.name", "redis")
            time.sleep(random.uniform(0.002, 0.008))

        # cache miss → fetch from DB
        with pg_svc.tracer.start_as_current_span("gorm.query", kind=SpanKind.CLIENT) as db_span:
            db_span.set_attribute("db.system.name", "postgresql")
            db_span.set_attribute("db.operation.name", "SELECT")
            db_span.set_attribute("db.query.text", "SELECT * FROM inventory_items ORDER BY created_at DESC LIMIT $1 OFFSET $2")
            db_span.set_attribute("db.collection.name", "inventory_items")
            db_span.set_attribute("pagination.page", page)
            db_span.set_attribute("pagination.size", page_size)
            db_span.set_attribute("service.peer.name", "postgresql")
            t_db = time.time()
            time.sleep(random.uniform(0.015, 0.06))
            db_duration.record((time.time() - t_db) * 1000, {"db.operation.name": "SELECT"})

        # cache set
        with redis_svc.tracer.start_as_current_span("redis.SET", kind=SpanKind.CLIENT) as r_span:
            r_span.set_attribute("db.system.name", "redis")
            r_span.set_attribute("db.operation.name", "SET")
            r_span.set_attribute("cache.key", cache_key)
            r_span.set_attribute("cache.ttl_seconds", 60)
            r_span.set_attribute("service.peer.name", "redis")
            time.sleep(random.uniform(0.002, 0.008))

        span.set_attribute("http.response.status_code", 200)
        span.set_attribute("response.item_count", page_size)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "GET", "http.route": "/api/v2/inventory/items", "http.response.status_code": "200"})
    req_duration.record(dur_ms, {"http.request.method": "GET"})
    api.logger.info("Inventory list served from DB (cache miss)", extra={"page": page, "cache_key": cache_key})
    print("  ✅ Scenario 2 — Pagination → Redis cache miss → DB → cache set")
except Exception as exc:
    print(f"  ❌ Scenario 2 — Pagination/cache: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — Gin validation: ShouldBindJSON → validator.v10 → 422
# ─────────────────────────────────────────────────────────────────────────────
try:
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "gin.handler.POST /api/v2/inventory/items", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("gin.route", "/api/v2/inventory/items")
        span.set_attribute("gin.handler_name", "createInventoryItem")
        span.set_attribute("http.request.method", "POST")

        with api.tracer.start_as_current_span(
            "gin.validation.ShouldBindJSON", kind=SpanKind.INTERNAL
        ) as val_span:
            val_span.set_attribute("validation.library", "validator.v10")
            val_span.set_attribute("validation.failed", True)
            val_span.set_attribute("validation.field", "price")
            val_span.set_attribute("validation.tag", "required,gt=0")
            time.sleep(random.uniform(0.001, 0.005))
            val_err = ValueError("Key: 'Item.Price' Error:Field validation for 'Price' failed on the 'gt' tag")
            val_span.record_exception(val_err, attributes={"exception.escaped": False})
            val_span.set_status(StatusCode.ERROR, "validation failed")
            val_span.set_attribute("error.type", type(val_err).__name__)

        span.set_attribute("http.response.status_code", 422)
        span.set_status(StatusCode.ERROR, "Unprocessable Entity")

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "POST", "http.route": "/api/v2/inventory/items", "http.response.status_code": "422"})
    req_duration.record(dur_ms, {"http.request.method": "POST"})
    api.logger.warning("Validation failed on POST /api/v2/inventory/items", extra={"validation_field": "price"})
    print("  ✅ Scenario 3 — ShouldBindJSON → validator.v10 → 422 Unprocessable Entity")
except Exception as exc:
    print(f"  ❌ Scenario 3 — Gin validation: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — Goroutine fan-out: 3 concurrent DB queries → WaitGroup → merge
# ─────────────────────────────────────────────────────────────────────────────
try:
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "gin.handler.GET /api/v2/inventory/summary", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("gin.route", "/api/v2/inventory/summary")
        span.set_attribute("gin.handler_name", "getInventorySummary")
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("go.goroutines", 3)

        with api.tracer.start_as_current_span(
            "goroutine.concurrent_fetch", kind=SpanKind.INTERNAL
        ) as fan_span:
            fan_span.set_attribute("go.goroutines", 3)
            fan_span.set_attribute("concurrency.pattern", "sync.WaitGroup")

            queries = [
                ("SELECT COUNT(*) FROM inventory_items WHERE status = 'active'", "active_count"),
                ("SELECT SUM(quantity) FROM inventory_items WHERE stock_level = 'low'", "low_stock_sum"),
                ("SELECT AVG(price) FROM inventory_items WHERE category = 'electronics'", "avg_price"),
            ]
            for stmt, label in queries:
                with pg_svc.tracer.start_as_current_span("gorm.query", kind=SpanKind.CLIENT) as db_span:
                    db_span.set_attribute("db.system.name", "postgresql")
                    db_span.set_attribute("db.operation.name", "SELECT")
                    db_span.set_attribute("db.query.text", stmt)
                    db_span.set_attribute("goroutine.label", label)
                    db_span.set_attribute("service.peer.name", "postgresql")
                    t_db = time.time()
                    time.sleep(random.uniform(0.01, 0.04))
                    db_duration.record((time.time() - t_db) * 1000, {"db.operation.name": "SELECT"})

            fan_span.add_event("goroutine.fan_out.complete", {"goroutine.count": 3, "goroutine.max_latency_ms": 45})

        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "GET", "http.route": "/api/v2/inventory/summary", "http.response.status_code": "200"})
    req_duration.record(dur_ms, {"http.request.method": "GET"})
    api.logger.info("Inventory summary aggregated via goroutine fan-out")
    print("  ✅ Scenario 4 — Goroutine fan-out: 3 concurrent DB queries → WaitGroup → merge")
except Exception as exc:
    print(f"  ❌ Scenario 4 — Goroutine fan-out: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 — GORM transaction: BEGIN → insert → update → audit → COMMIT
# ─────────────────────────────────────────────────────────────────────────────
try:
    tx_item_id = str(uuid.uuid4())
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "gin.handler.POST /api/v2/inventory/items/receive", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("gin.route", "/api/v2/inventory/items/receive")
        span.set_attribute("gin.handler_name", "receiveInventory")
        span.set_attribute("http.request.method", "POST")

        with pg_svc.tracer.start_as_current_span(
            "gorm.transaction", kind=SpanKind.CLIENT
        ) as tx_span:
            tx_span.set_attribute("db.system.name", "postgresql")
            tx_span.set_attribute("db.operation.name", "BEGIN")
            tx_span.set_attribute("transaction.id", tx_item_id)
            tx_span.set_attribute("service.peer.name", "postgresql")

            steps = [
                ("BEGIN",             "BEGIN TRANSACTION"),
                ("INSERT",            "INSERT INTO inventory_items (id, sku, quantity, price) VALUES ($1, $2, $3, $4)"),
                ("UPDATE",            "UPDATE stock_levels SET quantity = quantity + $1 WHERE sku = $2"),
                ("INSERT audit_log",  "INSERT INTO audit_log (table_name, operation, record_id, timestamp) VALUES ($1, $2, $3, NOW())"),
                ("COMMIT",            "COMMIT"),
            ]
            for op, stmt in steps:
                with pg_svc.tracer.start_as_current_span("gorm.query", kind=SpanKind.CLIENT) as db_span:
                    db_span.set_attribute("db.system.name", "postgresql")
                    db_span.set_attribute("db.operation.name", op)
                    db_span.set_attribute("db.query.text", stmt)
                    db_span.set_attribute("service.peer.name", "postgresql")
                    t_db = time.time()
                    time.sleep(random.uniform(0.005, 0.02))
                    db_duration.record((time.time() - t_db) * 1000, {"db.operation.name": op})

        span.set_attribute("http.response.status_code", 201)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "POST", "http.route": "/api/v2/inventory/items/receive", "http.response.status_code": "201"})
    req_duration.record(dur_ms, {"http.request.method": "POST"})
    api.logger.info("Inventory received via GORM transaction", extra={"item_id": tx_item_id})
    print("  ✅ Scenario 5 — GORM transaction: BEGIN → insert → update stock → audit → COMMIT")
except Exception as exc:
    print(f"  ❌ Scenario 5 — GORM transaction: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 — Graceful shutdown: SIGTERM → drain → flush OTel → exit
# ─────────────────────────────────────────────────────────────────────────────
try:
    with api.tracer.start_as_current_span(
        "gin.server.graceful_shutdown", kind=SpanKind.INTERNAL
    ) as span:
        span.set_attribute("shutdown.signal", "SIGTERM")
        span.set_attribute("shutdown.in_flight_requests", random.randint(0, 5))
        span.set_attribute("shutdown.timeout_seconds", 30)

        with api.tracer.start_as_current_span(
            "gin.server.drain_requests", kind=SpanKind.INTERNAL
        ) as drain_span:
            drain_span.set_attribute("drain.duration_ms", random.randint(50, 500))
            time.sleep(random.uniform(0.01, 0.03))

        with api.tracer.start_as_current_span(
            "otel.flush", kind=SpanKind.INTERNAL
        ) as flush_span:
            flush_span.set_attribute("otel.exporter", "otlp-http")
            flush_span.set_attribute("otel.flush.success", True)
            time.sleep(random.uniform(0.005, 0.015))

    api.logger.info("Gin server graceful shutdown complete", extra={"signal": "SIGTERM"})
    print("  ✅ Scenario 6 — Graceful shutdown: SIGTERM → drain → flush OTel → exit")
except Exception as exc:
    print(f"  ❌ Scenario 6 — Graceful shutdown: {exc}")

# ── Flush all ─────────────────────────────────────────────────────────────────
api.flush()
pg_svc.flush()
redis_svc.flush()

print(f"\n[{SVC}] Done. APM → {SVC} | Metrics: gin.request, db.client.operation.duration")
