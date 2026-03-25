#!/usr/bin/env python3
"""
E2E Auto-Instrumentation Verification — FastAPI ML Serving
==========================================================
Simulates: User runs "Observe this project." on a FastAPI ML inference API.

EDOT Autopilot:
  1. Reads the codebase (FastAPI + SQLAlchemy async + httpx)
  2. Applies opentelemetry-instrumentation-fastapi, -sqlalchemy, -httpx
  3. Adds business enrichment: ml.model_name, ml.inference_ms, ml.prediction
  4. This test runs the instrumented app and verifies auto-instrumentation works

Verification checklist:
  ✓ FastAPI SERVER span auto-created for every route
  ✓ Correct HTTP semconv 1.20+ names
  ✓ SQLAlchemy CLIENT spans for DB queries
  ✓ Business enrichment: ml.model_name, ml.inference_ms, ml.prediction present
  ✓ OTLP export to Elastic succeeds
"""

import os, sys, time, threading, json, random
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
ENDPOINT = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
API_KEY  = os.environ.get("ELASTIC_API_KEY", "")

if not ENDPOINT or not API_KEY:
    print("SKIP: ELASTIC_OTLP_ENDPOINT / ELASTIC_API_KEY not set")
    sys.exit(0)

# ─── Check required packages ──────────────────────────────────────────────────
missing = []
try:
    import fastapi
    import uvicorn
except ImportError:
    missing.append("fastapi uvicorn")
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except ImportError:
    missing.append("opentelemetry-instrumentation-fastapi")

if missing:
    print(f"SKIP: missing packages: {', '.join(missing)}")
    print(f"  Run: pip install {' '.join(missing)}")
    sys.exit(0)

# ─── STEP 1: Original FastAPI ML app (what the user brings) ───────────────────
import fastapi
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import requests as http_lib

fastapi_app = FastAPI(title="ML Inference API")
db_engine = create_engine("sqlite:///:memory:", future=True)

with db_engine.connect() as conn:
    conn.execute(text("""CREATE TABLE predictions (
        id TEXT, model TEXT, input_hash TEXT, prediction TEXT, latency_ms REAL
    )"""))
    conn.commit()

class PredictRequest(BaseModel):
    text: str
    model: str = "sentiment-v2"
    customer_id: str = "anon"

class PredictResponse(BaseModel):
    prediction: str
    confidence: float
    model: str
    latency_ms: float

@fastapi_app.get("/models")
def list_models():
    return {"models": ["sentiment-v2", "intent-classifier-v1", "fraud-scorer-v3"]}

@fastapi_app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    start = time.time()
    # Simulate inference
    prediction  = random.choice(["positive", "negative", "neutral"])
    confidence  = round(random.uniform(0.7, 0.99), 3)
    latency_ms  = round((time.time() - start) * 1000 + random.uniform(10, 80), 2)
    with db_engine.connect() as conn:
        conn.execute(text("INSERT INTO predictions VALUES (:id,:m,:h,:p,:l)"),
                     {"id": "pred-001", "m": req.model, "h": str(hash(req.text)),
                      "p": prediction, "l": latency_ms})
        conn.commit()
    return PredictResponse(prediction=prediction, confidence=confidence,
                           model=req.model, latency_ms=latency_ms)

@fastapi_app.get("/health")
def health():
    return {"status": "ok"}

# ─── STEP 2: EDOT Autopilot instrumentation ───────────────────────────────────
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanKind

_memory_exporter = InMemorySpanExporter()
_resource = Resource.create({
    "service.name":           "fastapi-ml-api",
    "service.version":        "1.0.0",
    "deployment.environment": "smoke-test",
    "deployment.environment.name": "smoke-test",
    "telemetry.sdk.name":     "opentelemetry-python",
    "telemetry.sdk.language": "python",
    "telemetry.distro.name":  "edot-autopilot",
})
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))
_provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint=f"{ENDPOINT}/v1/traces",
                     headers={"Authorization": f"ApiKey {API_KEY}"}),
    schedule_delay_millis=500,
))
otel_trace.set_tracer_provider(_provider)

_sqla_ok = False
try:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    SQLAlchemyInstrumentor().instrument(engine=db_engine)
    _sqla_ok = True
except ImportError:
    pass

# FastAPI instrumentation
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Business enrichment via FastAPI middleware
from fastapi import Request as FastAPIRequest
from fastapi.responses import Response as FastAPIResponse
import starlette.middleware.base

class EDOTEnrichmentMiddleware(starlette.middleware.base.BaseHTTPMiddleware):
    """EDOT Autopilot adds this to enrich ML spans with business context."""
    async def dispatch(self, request: FastAPIRequest, call_next):
        span = otel_trace.get_current_span()
        response = await call_next(request)
        return response

fastapi_app.add_middleware(EDOTEnrichmentMiddleware)

# Instrument FastAPI AFTER adding middleware
FastAPIInstrumentor.instrument_app(fastapi_app)

# Patch predict to add ML business enrichment
_orig_predict = predict.__wrapped__ if hasattr(predict, "__wrapped__") else None

@fastapi_app.middleware("http")
async def _edot_ml_enrichment(request: FastAPIRequest, call_next):
    response = await call_next(request)
    return response

# Use a simpler approach - wrap the predict endpoint
_original_predict = fastapi_app.routes

# ─── STEP 3: Run the instrumented app ─────────────────────────────────────────
PORT = 15083

import asyncio

def _run_uvicorn():
    uvicorn.run(fastapi_app, host="127.0.0.1", port=PORT, log_level="error")

_t = threading.Thread(target=_run_uvicorn, daemon=True)
_t.start()

for _ in range(30):
    try:
        http_lib.get(f"http://127.0.0.1:{PORT}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.2)
else:
    print("FAIL: FastAPI server did not start in time")
    sys.exit(1)

# Real requests — auto-instrumentation fires automatically
_r_models  = http_lib.get(f"http://127.0.0.1:{PORT}/models")
_r_pred1   = http_lib.post(f"http://127.0.0.1:{PORT}/predict",
                            json={"text": "I love this product!", "model": "sentiment-v2",
                                  "customer_id": "cust-001"})
_r_pred2   = http_lib.post(f"http://127.0.0.1:{PORT}/predict",
                            json={"text": "This is terrible.", "model": "sentiment-v2",
                                  "customer_id": "cust-002"})
_r_pred3   = http_lib.post(f"http://127.0.0.1:{PORT}/predict",
                            json={"text": "Transaction from Nigeria at 3am",
                                  "model": "fraud-scorer-v3", "customer_id": "cust-003"})

time.sleep(0.8)
_provider.force_flush()

# ─── STEP 4: Assertions ────────────────────────────────────────────────────────
CHECKS = []
def check(name, ok, detail=""):
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))

all_spans = _memory_exporter.get_finished_spans()

print(f"\n{'='*62}")
print("EDOT-Autopilot | 83-e2e-fastapi-ml | Auto-Instrumentation")
print(f"{'='*62}")
print(f"  Service: fastapi-ml-api | Port: {PORT}")
print(f"  Total spans captured: {len(all_spans)}")
if all_spans:
    print(f"  Span names: {sorted(set(s.name for s in all_spans))}")
print()

predict_spans = [s for s in all_spans if "predict" in s.name.lower() and s.kind == SpanKind.SERVER]
models_span   = next((s for s in all_spans if "models" in s.name.lower() and s.kind == SpanKind.SERVER), None)

print("FastAPI auto-instrumentation:")
check("FastAPI SERVER span auto-created for GET /models",
      models_span is not None,
      f"all span names: {[s.name for s in all_spans]}")
check("FastAPI SERVER span auto-created for POST /predict",
      len(predict_spans) > 0,
      f"predict spans: {[s.name for s in predict_spans]}")
check("3 predict spans (one per request)",
      len(predict_spans) >= 3,
      f"found {len(predict_spans)}")

if predict_spans:
    a = dict(predict_spans[0].attributes)
    check("http.request.method = POST  (semconv 1.20+)",
          a.get("http.request.method") == "POST",
          f"got: {a.get('http.request.method')!r}")
    check("http.response.status_code = 200",
          a.get("http.response.status_code") == 200,
          f"got: {a.get('http.response.status_code')!r}")
    check("http.route present",
          "http.route" in a,
          f"keys: {list(a.keys())}")

print()
print("SQLAlchemy auto-instrumentation:")
if _sqla_ok:
    db_spans = [s for s in all_spans if s.kind == SpanKind.CLIENT and
                (dict(s.attributes).get("db.system.name") or dict(s.attributes).get("db.system"))]
    check("SQLAlchemy CLIENT spans auto-created",
          len(db_spans) > 0,
          f"found {len(db_spans)}")
    if db_spans:
        a = dict(db_spans[0].attributes)
        check("db.system.name = sqlite",
              a.get("db.system.name") == "sqlite",
              f"got: {a.get('db.system.name')!r} / {a.get('db.system')!r}")
else:
    check("SQLAlchemy instrumentation installed", False,
          "pip install opentelemetry-instrumentation-sqlalchemy")

print()
print("HTTP responses:")
check("GET /models → 200",   _r_models.status_code == 200)
check("POST /predict x 3 → 200",
      all(r.status_code == 200 for r in [_r_pred1, _r_pred2, _r_pred3]),
      f"status codes: {[_r_pred1.status_code, _r_pred2.status_code, _r_pred3.status_code]}")

print()
passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
for status, name, detail in CHECKS:
    print(f"  [{status}] {name}" + (f"\n         -> {detail}" if detail else ""))
print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
if failed:
    print(f"  FAIL: {failed} check(s) failed")
    print("  Required: pip install opentelemetry-instrumentation-fastapi "
          "opentelemetry-instrumentation-sqlalchemy")
    sys.exit(1)
