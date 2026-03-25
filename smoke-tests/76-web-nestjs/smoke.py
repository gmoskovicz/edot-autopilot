#!/usr/bin/env python3
"""
Smoke test: NestJS — REST/GraphQL/Microservice/WebSocket/CQRS gateway.

Services modeled:
  web-nestjs-gateway → web-nestjs-users-service
                     → web-nestjs-events-service

Scenarios:
  1. REST controller: GET /users/:id → JwtAuthGuard → Service → TypeORM
  2. GraphQL resolver: query { user(id) { profile orders } } → DataLoader → 2 DB calls
  3. Microservice: TCP transport → @MessagePattern handler → EventEmitter → CQRS
  4. WebSocket gateway: @SubscribeMessage('chat') → broadcast → client ack
  5. CQRS: CreateUserCommand → CommandHandler → EventBus → UserCreatedEvent → EventHandler
  6. Interceptor chain: Logging → Transform → Cache → handler

Run:
    cd smoke-tests && python3 76-web-nestjs/smoke.py
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

NESTJS_ATTRS = {
    "framework":              "nestjs",
    "nestjs.version":         "10.3.0",
    "node.version":           "20.10.0",
    "telemetry.sdk.name":     "opentelemetry-node",
    "telemetry.sdk.language": "javascript",
}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
gateway       = O11yBootstrap("web-nestjs-gateway",       ENDPOINT, API_KEY, ENV, extra_resource_attrs=NESTJS_ATTRS)
users_svc     = O11yBootstrap("web-nestjs-users-service", ENDPOINT, API_KEY, ENV, extra_resource_attrs=NESTJS_ATTRS)
events_svc    = O11yBootstrap("web-nestjs-events-service",ENDPOINT, API_KEY, ENV, extra_resource_attrs=NESTJS_ATTRS)

# ── Metrics instruments ───────────────────────────────────────────────────────
req_counter      = gateway.meter.create_counter("http.server.request_count",       description="Total HTTP requests")
req_duration     = gateway.meter.create_histogram("http.server.duration_ms",       description="HTTP server request duration", unit="ms")
gql_duration     = gateway.meter.create_histogram("graphql.resolver.duration_ms",  description="GraphQL resolver latency", unit="ms")
cqrs_commands    = gateway.meter.create_counter("nestjs.cqrs.commands_processed",  description="CQRS commands processed")

def _active_ws_cb(options):
    yield Observation(random.randint(5, 40), {"gateway": "web-nestjs-gateway"})

gateway.meter.create_observable_gauge(
    "nestjs.websocket.active_connections", [_active_ws_cb],
    description="Active WebSocket connections")

SVC = "web-nestjs-gateway"
print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — REST controller: GET /users/:id → Guard → Service → TypeORM
# ─────────────────────────────────────────────────────────────────────────────
try:
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    carrier = {}
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "nestjs.controller.GET /users/:id", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("nestjs.controller", "UsersController")
        span.set_attribute("nestjs.handler", "findOne")
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("http.route", "/users/:id")
        span.set_attribute("url.path", f"/users/{user_id}")
        span.set_attribute("user.id", user_id)

        propagator.inject(carrier)

        with gateway.tracer.start_as_current_span(
            "nestjs.guard.JwtAuthGuard", kind=SpanKind.INTERNAL
        ) as guard_span:
            guard_span.set_attribute("nestjs.guard", "JwtAuthGuard")
            guard_span.set_attribute("nestjs.controller", "UsersController")
            guard_span.set_attribute("auth.token_valid", True)
            time.sleep(random.uniform(0.005, 0.02))

        with users_svc.tracer.start_as_current_span(
            "nestjs.service.UsersService.findOne", kind=SpanKind.INTERNAL
        ) as svc_span:
            svc_span.set_attribute("nestjs.provider", "UsersService")
            svc_span.set_attribute("nestjs.handler", "findOne")
            svc_span.set_attribute("user.id", user_id)

            with users_svc.tracer.start_as_current_span(
                "nestjs.typeorm.query", kind=SpanKind.CLIENT
            ) as db_span:
                db_span.set_attribute("db.system.name", "postgresql")
                db_span.set_attribute("db.operation.name", "SELECT")
                db_span.set_attribute("db.query.text", "SELECT * FROM users WHERE id = $1")
                db_span.set_attribute("db.collection.name", "users")
                db_span.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.01, 0.05))

        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_counter.add(1, {"http.request.method": "GET", "http.route": "/users/:id", "http.response.status_code": "200"})
    req_duration.record(dur_ms, {"http.request.method": "GET", "http.route": "/users/:id"})
    gateway.logger.info("REST GET /users/:id completed", extra={"user.id": user_id, "duration_ms": round(dur_ms, 2)})
    print("  ✅ Scenario 1 — REST controller GET /users/:id")
except Exception as exc:
    print(f"  ❌ Scenario 1 — REST controller: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — GraphQL resolver: query { user(id) { profile orders } } → DataLoader → 2 DB calls
# ─────────────────────────────────────────────────────────────────────────────
try:
    gql_user_id = f"usr_{uuid.uuid4().hex[:8]}"
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "nestjs.graphql.query", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("graphql.operation.type", "query")
        span.set_attribute("graphql.operation.name", "GetUser")
        span.set_attribute("graphql.document", "{ user(id: $id) { profile orders } }")
        span.set_attribute("user.id", gql_user_id)

        with users_svc.tracer.start_as_current_span(
            "nestjs.graphql.resolver.UserResolver.user", kind=SpanKind.INTERNAL
        ) as resolver_span:
            resolver_span.set_attribute("graphql.field.name", "user")
            resolver_span.set_attribute("graphql.operation.name", "GetUser")

            # DataLoader batches profile + orders into 2 DB calls
            with users_svc.tracer.start_as_current_span(
                "nestjs.typeorm.query", kind=SpanKind.CLIENT
            ) as db1:
                db1.set_attribute("db.system.name", "postgresql")
                db1.set_attribute("db.operation.name", "SELECT")
                db1.set_attribute("db.query.text", "SELECT * FROM user_profiles WHERE user_id = ANY($1)")
                db1.set_attribute("db.collection.name", "user_profiles")
                db1.set_attribute("dataloader.batch_size", random.randint(1, 10))
                db1.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.01, 0.04))

            with users_svc.tracer.start_as_current_span(
                "nestjs.typeorm.query", kind=SpanKind.CLIENT
            ) as db2:
                db2.set_attribute("db.system.name", "postgresql")
                db2.set_attribute("db.operation.name", "SELECT")
                db2.set_attribute("db.query.text", "SELECT * FROM orders WHERE user_id = ANY($1)")
                db2.set_attribute("db.collection.name", "orders")
                db2.set_attribute("dataloader.batch_size", random.randint(1, 10))
                db2.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.01, 0.06))

        span.set_attribute("http.response.status_code", 200)

    gql_ms = (time.time() - t0) * 1000
    gql_duration.record(gql_ms, {"graphql.operation.type": "query", "graphql.operation.name": "GetUser"})
    gateway.logger.info("GraphQL query GetUser completed", extra={"user.id": gql_user_id, "duration_ms": round(gql_ms, 2)})
    print("  ✅ Scenario 2 — GraphQL resolver with DataLoader batching")
except Exception as exc:
    print(f"  ❌ Scenario 2 — GraphQL resolver: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — Microservice: TCP transport → @MessagePattern → EventEmitter → CQRS
# ─────────────────────────────────────────────────────────────────────────────
try:
    pattern = "user.find"
    msg_id  = uuid.uuid4().hex
    carrier = {}

    with gateway.tracer.start_as_current_span(
        "nestjs.microservice.tcp", kind=SpanKind.PRODUCER
    ) as span:
        span.set_attribute("nestjs.microservice.transport", "TCP")
        span.set_attribute("nestjs.microservice.pattern", pattern)
        span.set_attribute("messaging.system", "nestjs-tcp")
        span.set_attribute("messaging.operation.type", "publish")
        span.set_attribute("messaging.message.id", msg_id)
        span.add_event("cqrs.command.dispatched", {"command.name": "CreateUserCommand"})
        propagator.inject(carrier)
        time.sleep(random.uniform(0.005, 0.02))

    with users_svc.tracer.start_as_current_span(
        "nestjs.microservice.tcp", kind=SpanKind.CONSUMER
    ) as span:
        span.set_attribute("nestjs.microservice.transport", "TCP")
        span.set_attribute("nestjs.microservice.pattern", pattern)
        span.set_attribute("nestjs.handler", "handleUserFind")
        span.set_attribute("messaging.message.id", msg_id)
        span.add_event("cqrs.event.published", {"event.name": "UserCreatedEvent"})

        with users_svc.tracer.start_as_current_span(
            "nestjs.event_emitter.emit", kind=SpanKind.INTERNAL
        ) as ev_span:
            ev_span.set_attribute("event.name", "user.found")
            ev_span.set_attribute("nestjs.cqrs.event", "UserFoundEvent")
            time.sleep(random.uniform(0.005, 0.015))

    gateway.logger.info("Microservice TCP message handled", extra={"pattern": pattern, "message_id": msg_id})
    print("  ✅ Scenario 3 — Microservice TCP transport → CQRS")
except Exception as exc:
    print(f"  ❌ Scenario 3 — Microservice pattern: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — WebSocket gateway: @SubscribeMessage('chat') → broadcast → ack
# ─────────────────────────────────────────────────────────────────────────────
try:
    client_id = f"ws_{uuid.uuid4().hex[:6]}"
    room_id   = f"room_{random.randint(1, 20)}"

    with gateway.tracer.start_as_current_span(
        "nestjs.websocket.message", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("nestjs.websocket.event", "chat")
        span.set_attribute("nestjs.websocket.gateway", "ChatGateway")
        span.set_attribute("websocket.client_id", client_id)
        span.set_attribute("websocket.room", room_id)
        span.set_attribute("messaging.system", "websocket")

        with gateway.tracer.start_as_current_span(
            "nestjs.websocket.broadcast", kind=SpanKind.INTERNAL
        ) as bc_span:
            bc_span.set_attribute("websocket.room", room_id)
            bc_span.set_attribute("websocket.recipients", random.randint(1, 15))
            time.sleep(random.uniform(0.002, 0.01))

        with gateway.tracer.start_as_current_span(
            "nestjs.websocket.ack", kind=SpanKind.INTERNAL
        ) as ack_span:
            ack_span.set_attribute("websocket.client_id", client_id)
            ack_span.set_attribute("websocket.ack_received", True)
            time.sleep(random.uniform(0.001, 0.005))

    gateway.logger.info("WebSocket chat message handled", extra={"client_id": client_id, "room": room_id})
    print("  ✅ Scenario 4 — WebSocket @SubscribeMessage('chat') → broadcast → ack")
except Exception as exc:
    print(f"  ❌ Scenario 4 — WebSocket gateway: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 — CQRS: CreateUserCommand → CommandHandler → EventBus → EventHandler
# ─────────────────────────────────────────────────────────────────────────────
try:
    new_user_id = f"usr_{uuid.uuid4().hex[:8]}"
    command_id  = uuid.uuid4().hex

    with gateway.tracer.start_as_current_span(
        "nestjs.cqrs.command", kind=SpanKind.INTERNAL
    ) as span:
        span.set_attribute("nestjs.cqrs.command", "CreateUserCommand")
        span.set_attribute("nestjs.cqrs.handler", "CreateUserCommandHandler")
        span.set_attribute("command.id", command_id)
        span.set_attribute("user.id", new_user_id)

        with users_svc.tracer.start_as_current_span(
            "nestjs.typeorm.query", kind=SpanKind.CLIENT
        ) as db_span:
            db_span.set_attribute("db.system.name", "postgresql")
            db_span.set_attribute("db.operation.name", "INSERT")
            db_span.set_attribute("db.query.text", "INSERT INTO users (id, email, created_at) VALUES ($1, $2, $3)")
            db_span.set_attribute("db.collection.name", "users")
            db_span.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.01, 0.04))

        with gateway.tracer.start_as_current_span(
            "nestjs.cqrs.event_bus.publish", kind=SpanKind.INTERNAL
        ) as ev_span:
            ev_span.set_attribute("nestjs.cqrs.event", "UserCreatedEvent")
            ev_span.set_attribute("user.id", new_user_id)

            with events_svc.tracer.start_as_current_span(
                "nestjs.cqrs.event_handler.UserCreatedHandler", kind=SpanKind.INTERNAL
            ) as handler_span:
                handler_span.set_attribute("nestjs.cqrs.event", "UserCreatedEvent")
                handler_span.set_attribute("user.id", new_user_id)
                time.sleep(random.uniform(0.005, 0.02))

    cqrs_commands.add(1, {"command": "CreateUserCommand", "status": "success"})
    gateway.logger.info("CQRS CreateUserCommand executed", extra={"command_id": command_id, "user_id": new_user_id})
    print("  ✅ Scenario 5 — CQRS CreateUserCommand → EventBus → UserCreatedEvent")
except Exception as exc:
    print(f"  ❌ Scenario 5 — CQRS flow: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 — Interceptor chain: Logging → Transform → Cache → handler
# ─────────────────────────────────────────────────────────────────────────────
try:
    route_user_id = f"usr_{uuid.uuid4().hex[:8]}"
    cache_hit = random.choice([True, False])
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "nestjs.controller.GET /users/:id", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("nestjs.controller", "UsersController")
        span.set_attribute("nestjs.handler", "findOne")
        span.set_attribute("http.request.method", "GET")
        span.set_attribute("http.route", "/users/:id")
        span.set_attribute("user.id", route_user_id)

        interceptors = ["LoggingInterceptor", "TransformInterceptor", "CacheInterceptor"]
        for interceptor in interceptors:
            with gateway.tracer.start_as_current_span(
                f"nestjs.interceptor.{interceptor}", kind=SpanKind.INTERNAL
            ) as int_span:
                int_span.set_attribute("nestjs.interceptor", interceptor)
                int_span.set_attribute("nestjs.controller", "UsersController")
                time.sleep(random.uniform(0.002, 0.008))

        if not cache_hit:
            with users_svc.tracer.start_as_current_span(
                "nestjs.typeorm.query", kind=SpanKind.CLIENT
            ) as db_span:
                db_span.set_attribute("db.system.name", "postgresql")
                db_span.set_attribute("db.operation.name", "SELECT")
                db_span.set_attribute("db.query.text", "SELECT * FROM users WHERE id = $1")
                db_span.set_attribute("cache.hit", False)
                db_span.set_attribute("service.peer.name", "postgresql")
                time.sleep(random.uniform(0.01, 0.05))
        else:
            with gateway.tracer.start_as_current_span(
                "nestjs.cache.hit", kind=SpanKind.INTERNAL
            ) as cache_span:
                cache_span.set_attribute("cache.hit", True)
                cache_span.set_attribute("cache.key", f"user:{route_user_id}")
                time.sleep(random.uniform(0.001, 0.005))

        span.set_attribute("http.response.status_code", 200)
        span.set_attribute("cache.hit", cache_hit)

    dur_ms = (time.time() - t0) * 1000
    req_counter.add(1, {"http.request.method": "GET", "http.route": "/users/:id", "http.response.status_code": "200"})
    req_duration.record(dur_ms, {"http.request.method": "GET", "http.route": "/users/:id"})
    gateway.logger.info("Interceptor chain request completed",
                        extra={"user.id": route_user_id, "cache_hit": cache_hit, "duration_ms": round(dur_ms, 2)})
    print(f"  ✅ Scenario 6 — Interceptor chain (Logging→Transform→Cache) cache_hit={cache_hit}")
except Exception as exc:
    print(f"  ❌ Scenario 6 — Interceptor chain: {exc}")

# ── Flush all ─────────────────────────────────────────────────────────────────
gateway.flush()
users_svc.flush()
events_svc.flush()

print(f"\n[{SVC}] Done. APM → {SVC} | Metrics: http.server.request_count, nestjs.cqrs.commands_processed")
