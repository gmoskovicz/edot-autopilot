#!/usr/bin/env python3
"""
Smoke test: FastAPI — ML inference API with DI, background tasks, WebSocket, async SQLAlchemy.

Services modeled:
  web-fastapi-ml-api → web-fastapi-celery-worker
                     → web-fastapi-postgres

Scenarios:
  1. Dependency injection: Depends(get_db) → Depends(get_current_user) → endpoint
  2. Background task: return response immediately → BackgroundTask → webhooks
  3. WebSocket endpoint: ws://api/ws/stream → accept → send predictions → close
  4. Pydantic v2 validation: request body → model → custom validator → 422
  5. async SQLAlchemy: async with session → select() → scalars() → multiple awaits
  6. Lifespan event: startup → load ML model → warmup → ready; shutdown → flush queues

Run:
    cd smoke-tests && python3 79-web-fastapi/smoke.py
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

FASTAPI_ATTRS = {
    "framework":              "fastapi",
    "fastapi.version":        "0.109.0",
    "python.version":         "3.11.6",
    "telemetry.sdk.name":     "opentelemetry-python",
    "telemetry.sdk.language": "python",
}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
api     = O11yBootstrap("web-fastapi-ml-api",      ENDPOINT, API_KEY, ENV, extra_resource_attrs=FASTAPI_ATTRS)
celery  = O11yBootstrap("web-fastapi-celery-worker",ENDPOINT, API_KEY, ENV, extra_resource_attrs=FASTAPI_ATTRS)
pg_svc  = O11yBootstrap("web-fastapi-postgres",    ENDPOINT, API_KEY, ENV, extra_resource_attrs=FASTAPI_ATTRS)

# ── Metrics instruments ───────────────────────────────────────────────────────
req_total    = api.meter.create_counter("fastapi.request",              description="Total FastAPI requests")
req_duration = api.meter.create_histogram("fastapi.request.duration",   description="FastAPI request latency", unit="ms")
ml_duration  = api.meter.create_histogram("ml.inference_duration_ms",   description="ML model inference latency", unit="ms")

def _active_ws_cb(options):
    yield Observation(random.randint(0, 25), {"endpoint": "/api/ws/stream"})

api.meter.create_observable_gauge(
    "fastapi.active_websockets", [_active_ws_cb],
    description="Active WebSocket connections")

SVC = "web-fastapi-ml-api"
print(f"\n[{SVC}] Sending traces + logs + metrics to {ENDPOINT.split('@')[-1].split('/')[0]}...")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Dependency injection: Depends(get_db) → Depends(get_current_user) → endpoint
# ─────────────────────────────────────────────────────────────────────────────
try:
    user_id  = f"usr_{uuid.uuid4().hex[:8]}"
    api_key  = f"sk-{uuid.uuid4().hex[:16]}"
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "fastapi.request.POST /api/v1/predict", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("fastapi.route", "/api/v1/predict")
        span.set_attribute("fastapi.response_model", "PredictionResponse")
        span.set_attribute("http.request.method", "POST")
        span.set_attribute("http.route", "/api/v1/predict")

        with api.tracer.start_as_current_span(
            "fastapi.dependency.get_db", kind=SpanKind.INTERNAL
        ) as dep_span:
            dep_span.set_attribute("fastapi.dependency", "get_db")
            dep_span.set_attribute("db.system.name", "postgresql")
            dep_span.set_attribute("sqlalchemy.pool.checkout", True)
            time.sleep(random.uniform(0.002, 0.008))

        with api.tracer.start_as_current_span(
            "fastapi.dependency.verify_api_key", kind=SpanKind.INTERNAL
        ) as dep_span:
            dep_span.set_attribute("fastapi.dependency", "verify_api_key")
            dep_span.set_attribute("auth.api_key_prefix", api_key[:8])
            time.sleep(random.uniform(0.001, 0.005))

        with api.tracer.start_as_current_span(
            "fastapi.dependency.get_current_user", kind=SpanKind.INTERNAL
        ) as dep_span:
            dep_span.set_attribute("fastapi.dependency", "get_current_user")
            dep_span.set_attribute("user.id", user_id)
            dep_span.set_attribute("auth.scopes", "predict:read")
            time.sleep(random.uniform(0.003, 0.01))

        # Inference
        t_inf = time.time()
        with api.tracer.start_as_current_span(
            "ml.inference", kind=SpanKind.INTERNAL
        ) as ml_span:
            ml_span.set_attribute("ml.model_name", "fraud-detection-v3")
            ml_span.set_attribute("ml.model_version", "1.2.0")
            ml_span.set_attribute("ml.input_tokens", random.randint(10, 512))
            inf_ms = random.uniform(20, 120)
            time.sleep(inf_ms / 1000)
            ml_span.set_attribute("ml.inference_time_ms", round(inf_ms, 2))
            ml_span.add_event("ml.model.loaded", {"ml.model_name": "fraud-detection-v3", "ml.load_ms": 340})
            ml_span.add_event("ml.inference.complete", {"ml.output_tokens": 128, "ml.inference_ms": 45})

        ml_duration.record(inf_ms, {"ml.model_name": "fraud-detection-v3"})
        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "POST", "fastapi.route": "/api/v1/predict", "http.response.status_code": "200"})
    req_duration.record(dur_ms, {"fastapi.route": "/api/v1/predict"})
    api.logger.info("ML prediction served", extra={"user_id": user_id, "inference_ms": round(inf_ms, 2)})
    print("  ✅ Scenario 1 — Dependency injection Depends(get_db) → Depends(get_current_user) → predict")
except Exception as exc:
    print(f"  ❌ Scenario 1 — Dependency injection: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — Background task: return response → BackgroundTask → webhooks
# ─────────────────────────────────────────────────────────────────────────────
try:
    task_id    = uuid.uuid4().hex
    webhook_url = "https://hooks.example.com/predictions"
    carrier    = {}
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "fastapi.request.POST /api/v1/predict/async", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("fastapi.route", "/api/v1/predict/async")
        span.set_attribute("fastapi.response_model", "AsyncPredictionResponse")
        span.set_attribute("http.request.method", "POST")
        span.set_attribute("task.id", task_id)
        time.sleep(random.uniform(0.002, 0.008))
        span.set_attribute("http.response.status_code", 202)
        propagator.inject(carrier)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "POST", "fastapi.route": "/api/v1/predict/async", "http.response.status_code": "202"})
    req_duration.record(dur_ms, {"fastapi.route": "/api/v1/predict/async"})
    api.logger.info("Async prediction accepted, background task enqueued", extra={"task_id": task_id})

    # Background task runs after response is sent
    with api.tracer.start_as_current_span(
        "fastapi.background_task", kind=SpanKind.INTERNAL
    ) as bg_span:
        bg_span.set_attribute("background_task.name", "send_prediction_webhook")
        bg_span.set_attribute("task.id", task_id)

        with celery.tracer.start_as_current_span(
            "celery.task.predict", kind=SpanKind.CONSUMER
        ) as cel_span:
            cel_span.set_attribute("celery.task_id", task_id)
            cel_span.set_attribute("celery.task_name", "tasks.run_prediction")
            cel_span.set_attribute("celery.queue", "predictions")
            cel_span.set_attribute("messaging.operation.type", "process")
            cel_span.set_attribute("ml.model_name", "fraud-detection-v3")
            t_inf = time.time()
            time.sleep(random.uniform(0.05, 0.15))
            inf_ms = (time.time() - t_inf) * 1000
            cel_span.set_attribute("ml.inference_time_ms", round(inf_ms, 2))
            ml_duration.record(inf_ms, {"ml.model_name": "fraud-detection-v3"})

        with api.tracer.start_as_current_span(
            "http.client.POST webhook", kind=SpanKind.CLIENT
        ) as wh_span:
            wh_span.set_attribute("http.request.method", "POST")
            wh_span.set_attribute("url.full", webhook_url)
            wh_span.set_attribute("task.id", task_id)
            wh_span.set_attribute("service.peer.name", "hooks.example.com")
            time.sleep(random.uniform(0.01, 0.04))

    api.logger.info("Background task completed, webhook sent", extra={"task_id": task_id})
    print("  ✅ Scenario 2 — Background task: 202 returned → Celery predict → webhook sent")
except Exception as exc:
    print(f"  ❌ Scenario 2 — Background task: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — WebSocket endpoint: accept → stream predictions → close
# ─────────────────────────────────────────────────────────────────────────────
try:
    ws_id    = f"ws_{uuid.uuid4().hex[:8]}"
    n_frames = random.randint(3, 8)

    with api.tracer.start_as_current_span(
        "fastapi.websocket", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("fastapi.route", "/api/ws/stream")
        span.set_attribute("websocket.id", ws_id)
        span.set_attribute("messaging.system", "websocket")

        with api.tracer.start_as_current_span(
            "websocket.accept", kind=SpanKind.INTERNAL
        ) as acc_span:
            acc_span.set_attribute("websocket.id", ws_id)
            time.sleep(random.uniform(0.002, 0.008))

        for i in range(n_frames):
            with api.tracer.start_as_current_span(
                "websocket.send_frame", kind=SpanKind.INTERNAL
            ) as fr_span:
                fr_span.set_attribute("websocket.id", ws_id)
                fr_span.set_attribute("websocket.frame_index", i)
                fr_span.set_attribute("ml.model_name", "fraud-detection-v3")
                fr_span.set_attribute("ml.inference_time_ms", round(random.uniform(15, 80), 2))
                time.sleep(random.uniform(0.01, 0.03))

        with api.tracer.start_as_current_span(
            "websocket.close", kind=SpanKind.INTERNAL
        ) as cls_span:
            cls_span.set_attribute("websocket.id", ws_id)
            cls_span.set_attribute("websocket.close_code", 1000)
            time.sleep(random.uniform(0.001, 0.005))

        span.set_attribute("websocket.frames_sent", n_frames)

    api.logger.info("WebSocket stream completed", extra={"ws_id": ws_id, "frames_sent": n_frames})
    print(f"  ✅ Scenario 3 — WebSocket /api/ws/stream → {n_frames} prediction frames → close")
except Exception as exc:
    print(f"  ❌ Scenario 3 — WebSocket endpoint: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — Pydantic v2 validation: request body → model → custom validator → 422
# ─────────────────────────────────────────────────────────────────────────────
try:
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "fastapi.request.POST /api/v1/predict", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("fastapi.route", "/api/v1/predict")
        span.set_attribute("http.request.method", "POST")

        with api.tracer.start_as_current_span(
            "pydantic.validation", kind=SpanKind.INTERNAL
        ) as val_span:
            val_span.set_attribute("pydantic.model", "PredictionRequest")
            val_span.set_attribute("pydantic.version", "2.5.3")

            # Simulate validation error on 'text' field
            val_err = ValueError("Value error: text field must be between 1 and 512 characters [type=value_error]")
            val_span.set_attribute("pydantic.validation_error", "text")
            val_span.set_attribute("pydantic.error_count", 1)
            val_span.record_exception(val_err, attributes={"exception.escaped": False})
            val_span.set_status(StatusCode.ERROR, "Pydantic validation failed")
            val_span.set_attribute("error.type", type(val_err).__name__)
            time.sleep(random.uniform(0.001, 0.005))

        span.set_attribute("http.response.status_code", 422)
        span.set_status(StatusCode.ERROR, "Unprocessable Entity")

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "POST", "fastapi.route": "/api/v1/predict", "http.response.status_code": "422"})
    req_duration.record(dur_ms, {"fastapi.route": "/api/v1/predict"})
    api.logger.warning("Pydantic v2 validation error on POST /api/v1/predict",
                       extra={"field": "text", "error_count": 1})
    print("  ✅ Scenario 4 — Pydantic v2 validation → custom validator → 422 Unprocessable Entity")
except Exception as exc:
    print(f"  ❌ Scenario 4 — Pydantic validation: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 5 — async SQLAlchemy: async with session → select() → scalars() → awaits
# ─────────────────────────────────────────────────────────────────────────────
try:
    model_id = f"model_{uuid.uuid4().hex[:8]}"
    t0 = time.time()

    with api.tracer.start_as_current_span(
        "fastapi.request.GET /api/v1/models", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("fastapi.route", "/api/v1/models")
        span.set_attribute("http.request.method", "GET")

        with pg_svc.tracer.start_as_current_span(
            "sqlalchemy.async.select", kind=SpanKind.CLIENT
        ) as sa_span:
            sa_span.set_attribute("db.system.name", "postgresql")
            sa_span.set_attribute("db.operation.name", "SELECT")
            sa_span.set_attribute("db.query.text", "SELECT ml_models.id, ml_models.name, ml_models.version FROM ml_models WHERE is_active = true")
            sa_span.set_attribute("sqlalchemy.orm_mode", "async")
            sa_span.set_attribute("sqlalchemy.awaits", 2)
            sa_span.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.01, 0.04))

        with pg_svc.tracer.start_as_current_span(
            "sqlalchemy.async.select", kind=SpanKind.CLIENT
        ) as sa_span2:
            sa_span2.set_attribute("db.system.name", "postgresql")
            sa_span2.set_attribute("db.operation.name", "SELECT")
            sa_span2.set_attribute("db.query.text", "SELECT model_metrics.* FROM model_metrics WHERE model_id = :model_id ORDER BY evaluated_at DESC LIMIT 10")
            sa_span2.set_attribute("sqlalchemy.orm_mode", "async")
            sa_span2.set_attribute("sqlalchemy.awaits", 1)
            sa_span2.set_attribute("service.peer.name", "postgresql")
            time.sleep(random.uniform(0.008, 0.03))

        span.set_attribute("http.response.status_code", 200)

    dur_ms = (time.time() - t0) * 1000
    req_total.add(1, {"http.request.method": "GET", "fastapi.route": "/api/v1/models", "http.response.status_code": "200"})
    req_duration.record(dur_ms, {"fastapi.route": "/api/v1/models"})
    api.logger.info("async SQLAlchemy queries completed", extra={"duration_ms": round(dur_ms, 2)})
    print("  ✅ Scenario 5 — async SQLAlchemy: async with session → select() → scalars() → multiple awaits")
except Exception as exc:
    print(f"  ❌ Scenario 5 — async SQLAlchemy: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Scenario 6 — Lifespan event: startup → load ML model → warmup → ready; shutdown → flush
# ─────────────────────────────────────────────────────────────────────────────
try:
    with api.tracer.start_as_current_span(
        "fastapi.lifespan.startup", kind=SpanKind.INTERNAL
    ) as span:
        span.set_attribute("lifespan.event", "startup")
        span.set_attribute("ml.model_name", "fraud-detection-v3")

        with api.tracer.start_as_current_span(
            "ml.load_model", kind=SpanKind.INTERNAL
        ) as load_span:
            load_span.set_attribute("ml.model_name", "fraud-detection-v3")
            load_span.set_attribute("ml.model_path", "/models/fraud-detection-v3.pt")
            load_span.set_attribute("ml.model_size_mb", 438)
            time.sleep(random.uniform(0.05, 0.15))

        with api.tracer.start_as_current_span(
            "ml.warmup", kind=SpanKind.INTERNAL
        ) as wu_span:
            wu_span.set_attribute("ml.model_name", "fraud-detection-v3")
            wu_span.set_attribute("ml.warmup_batches", 3)
            t_wu = time.time()
            time.sleep(random.uniform(0.03, 0.08))
            wu_span.set_attribute("ml.warmup_duration_ms", round((time.time() - t_wu) * 1000, 2))

        span.set_attribute("lifespan.ready", True)

    api.logger.info("FastAPI lifespan startup complete: ML model loaded and warmed up",
                    extra={"model": "fraud-detection-v3", "model_version": "3.0"})

    # Simulate shutdown sequence
    with api.tracer.start_as_current_span(
        "fastapi.lifespan.shutdown", kind=SpanKind.INTERNAL
    ) as span:
        span.set_attribute("lifespan.event", "shutdown")

        with api.tracer.start_as_current_span(
            "celery.flush_queues", kind=SpanKind.INTERNAL
        ) as cel_span:
            cel_span.set_attribute("celery.pending_tasks", random.randint(0, 10))
            time.sleep(random.uniform(0.01, 0.04))

        with api.tracer.start_as_current_span(
            "otel.flush", kind=SpanKind.INTERNAL
        ) as fl_span:
            fl_span.set_attribute("otel.exporter", "otlp-http")
            time.sleep(random.uniform(0.005, 0.015))

    api.logger.info("FastAPI lifespan shutdown complete")
    print("  ✅ Scenario 6 — Lifespan startup (load ML → warmup → ready) & shutdown (flush queues)")
except Exception as exc:
    print(f"  ❌ Scenario 6 — Lifespan event: {exc}")

# ── Flush all ─────────────────────────────────────────────────────────────────
api.flush()
celery.flush()
pg_svc.flush()

print(f"\n[{SVC}] Done. APM → {SVC} | Metrics: fastapi.request, ml.inference_duration_ms")
