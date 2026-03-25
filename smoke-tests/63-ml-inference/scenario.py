#!/usr/bin/env python3
"""
ML Inference Platform — Distributed Tracing Scenario
======================================================

Services modeled:
  inference-gateway → result-cache (Redis)
                    → ab-testing-service
                    → feature-store
                    → model-registry
                    → serving-engine
                    → explainability-service

25 trace scenarios with realistic error mix:
  55% cache hit (result-cache returns immediately)
  20% cache miss → full inference
  10% model cold start (loading delay)
   8% feature store staleness warning
   5% GPU OOM → failover to CPU
   2% model version mismatch

Run:
    cd smoke-tests
    python3 63-ml-inference/scenario.py
"""

import os, sys, uuid, time, random
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

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
gateway    = O11yBootstrap("inference-gateway",      ENDPOINT, API_KEY, ENV)
cache      = O11yBootstrap("result-cache",           ENDPOINT, API_KEY, ENV)
abtesting  = O11yBootstrap("ab-testing-service",     ENDPOINT, API_KEY, ENV)
features   = O11yBootstrap("feature-store",          ENDPOINT, API_KEY, ENV)
registry   = O11yBootstrap("model-registry",         ENDPOINT, API_KEY, ENV)
serving    = O11yBootstrap("serving-engine",         ENDPOINT, API_KEY, ENV)
explain    = O11yBootstrap("explainability-service", ENDPOINT, API_KEY, ENV)

# ── Metrics instruments ───────────────────────────────────────────────────────
# inference-gateway
gw_requests   = gateway.meter.create_counter("inference.requests",          description="Total inference requests")
gw_latency    = gateway.meter.create_histogram("inference.latency_ms",      description="End-to-end inference latency", unit="ms")
gw_cache_hits = gateway.meter.create_counter("inference.cache_hits",        description="Cache hit count")
gw_errors     = gateway.meter.create_counter("inference.errors",            description="Inference errors by type")

# result-cache
cache_gets    = cache.meter.create_counter("cache.gets",                    description="Cache GET operations")
cache_sets    = cache.meter.create_counter("cache.sets",                    description="Cache SET operations")
cache_latency = cache.meter.create_histogram("cache.latency_ms",            description="Cache operation latency", unit="ms")

# feature-store
feat_fetches  = features.meter.create_counter("feature.fetches",            description="Feature retrieval count")
feat_stale    = features.meter.create_counter("feature.stale_warnings",     description="Stale feature warnings")
feat_latency  = features.meter.create_histogram("feature.latency_ms",       description="Feature fetch latency", unit="ms")
feat_count    = features.meter.create_histogram("feature.count",            description="Features per request")

# serving-engine
srv_requests  = serving.meter.create_counter("serving.requests",            description="Model inference calls")
srv_latency   = serving.meter.create_histogram("serving.inference_ms",      description="Model inference latency", unit="ms")
srv_gpu_oom   = serving.meter.create_counter("serving.gpu_oom",             description="GPU OOM events")
srv_cold_start= serving.meter.create_counter("serving.cold_starts",         description="Model cold start events")
gpu_mem_used  = serving.meter.create_histogram("gpu.memory_used_mb",        description="GPU memory usage", unit="MB")

# ab-testing
ab_assignments= abtesting.meter.create_counter("ab_test.assignments",       description="A/B test variant assignments")

# explainability
exp_requests  = explain.meter.create_counter("explainability.requests",     description="Explainability requests")
exp_latency   = explain.meter.create_histogram("explainability.duration_ms",description="SHAP computation latency", unit="ms")

# Observable gauge callbacks
def _gpu_utilization_cb(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.uniform(0.6, 0.95), {"device": "cuda:0"})

def _model_cache_cb(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.randint(2, 8), {"serving_engine": "triton"})

serving.meter.create_observable_gauge(
    "serving.gpu_utilization", [_gpu_utilization_cb],
    description="GPU utilization ratio")
serving.meter.create_observable_gauge(
    "serving.model_cache_count", [_model_cache_cb],
    description="Number of models loaded in serving cache")


# ── ML model catalog ──────────────────────────────────────────────────────────
MODELS = [
    {"name": "customer-churn-xgb",       "framework": "xgboost",    "task": "classification",
     "version": "3.2.1", "latest": "3.2.1", "feature_count": 84,  "gpu_required": False},
    {"name": "rec-engine-pytorch",        "framework": "pytorch",    "task": "ranking",
     "version": "7.1.0", "latest": "7.2.0", "feature_count": 256, "gpu_required": True},
    {"name": "fraud-rf-ensemble",         "framework": "sklearn",    "task": "classification",
     "version": "2.0.5", "latest": "2.0.5", "feature_count": 147, "gpu_required": False},
    {"name": "price-regression-lgbm",     "framework": "lightgbm",   "task": "regression",
     "version": "1.4.2", "latest": "1.4.2", "feature_count": 62,  "gpu_required": False},
    {"name": "nlp-sentiment-bert",        "framework": "pytorch",    "task": "classification",
     "version": "4.0.1", "latest": "4.1.0", "feature_count": 512, "gpu_required": True},
    {"name": "ctr-prediction-tf",         "framework": "tensorflow", "task": "classification",
     "version": "9.3.2", "latest": "9.3.2", "feature_count": 320, "gpu_required": True},
    {"name": "anomaly-isolation-forest",  "framework": "sklearn",    "task": "classification",
     "version": "1.1.0", "latest": "1.1.0", "feature_count": 38,  "gpu_required": False},
]

PREDICTION_CLASSES = {
    "classification": ["class_0", "class_1"],
    "ranking":        ["rank_1", "rank_2", "rank_3", "rank_5", "rank_10"],
    "regression":     ["value"],
}

REGULATED_INDUSTRIES = ["financial_services", "healthcare", "insurance", "lending"]
CALLER_INDUSTRIES    = ["ecommerce", "financial_services", "healthcare", "saas",
                         "gaming", "insurance", "media", "logistics"]

AB_TEST_CONFIG = {
    "customer-churn-xgb":   {"test_id": "churn-v3-vs-v4", "variants": ["control", "treatment"], "split": 0.5},
    "rec-engine-pytorch":   {"test_id": "rec-latency-opt", "variants": ["baseline", "optimized"], "split": 0.3},
    "nlp-sentiment-bert":   {"test_id": "bert-vs-distilbert", "variants": ["bert", "distilbert"], "split": 0.5},
    "ctr-prediction-tf":    {"test_id": "ctr-feature-ablation", "variants": ["full", "lite"], "split": 0.4},
}


# ── Helper ─────────────────────────────────────────────────────────────────────
def inject_traceparent(span) -> str:
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"

def extract_context(tp: str):
    return propagator.extract({"traceparent": tp})


# ── Service functions ──────────────────────────────────────────────────────────

def svc_result_cache(request_id: str, model: dict, entity_id: str,
                      parent_tp: str, cache_hit: bool = True) -> tuple:
    """Check Redis cache for existing inference result."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()
    cache_key = f"infer:{model['name']}:{entity_id}:{model['version']}"

    with gateway.tracer.start_as_current_span(
        "redis.client.result_cache", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"db.system": "redis", "net.peer.name": "result-cache",
                    "db.operation": "GET", "db.redis.database_index": 2,
                    "cache.key": cache_key, "request.id": request_id,
                    "model.name": model["name"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with cache.tracer.start_as_current_span(
            "cache.get", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"db.system": "redis", "db.operation": "GET",
                        "cache.key": cache_key, "request.id": request_id,
                        "model.name": model["name"], "model.version": model["version"],
                        "cache.ttl_seconds": 300, "cache.backend": "redis-cluster-7.2"}
        ) as entry_span:
            time.sleep(random.uniform(0.002, 0.01))  # redis is fast

            hit = cache_hit and random.random() < 0.75  # not always a hit even if expected
            entry_span.set_attribute("cache.hit",      hit)
            entry_span.set_attribute("cache.key",      cache_key)

            dur_ms = (time.time() - t0) * 1000
            cache_gets.add(1, attributes={"cache.hit": str(hit), "model.name": model["name"]})
            cache_latency.record(dur_ms, attributes={"db.operation": "GET"})

            if hit:
                prediction_class = random.choice(PREDICTION_CLASSES.get(model["task"], ["value"]))
                confidence       = round(random.uniform(0.65, 0.99), 4)
                entry_span.set_attribute("cache.prediction_class", prediction_class)
                entry_span.set_attribute("cache.confidence",       confidence)
                cache.logger.info(
                    f"cache HIT: {cache_key} ({model['task']})",
                    extra={"request.id": request_id, "cache.key": cache_key,
                           "model.name": model["name"], "cache.hit": True,
                           "prediction.class": prediction_class, "prediction.confidence": confidence}
                )
                return True, {"class": prediction_class, "confidence": confidence}, inject_traceparent(entry_span)
            else:
                cache.logger.info(
                    f"cache MISS: {cache_key}",
                    extra={"request.id": request_id, "cache.key": cache_key,
                           "model.name": model["name"], "cache.hit": False}
                )
                return False, None, inject_traceparent(entry_span)


def svc_ab_testing(request_id: str, model: dict, entity_id: str,
                    parent_tp: str) -> tuple:
    """Determine A/B test variant for this request."""
    parent_ctx = extract_context(parent_tp)

    with gateway.tracer.start_as_current_span(
        "http.client.ab_testing", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "GET", "net.peer.name": "ab-testing-service",
                    "http.url": "http://ab-testing-service/api/v1/assign",
                    "request.id": request_id, "model.name": model["name"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        ab_config = AB_TEST_CONFIG.get(model["name"])
        variant   = "default"
        test_id   = "none"

        with abtesting.tracer.start_as_current_span(
            "ab_test.assign_variant", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "GET", "http.route": "/api/v1/assign",
                        "request.id": request_id, "model.name": model["name"],
                        "entity.id": entity_id,
                        "ab_test.active": ab_config is not None}
        ) as entry_span:
            time.sleep(random.uniform(0.005, 0.02))

            if ab_config:
                test_id = ab_config["test_id"]
                variant = random.choices(
                    ab_config["variants"],
                    weights=[1 - ab_config["split"], ab_config["split"]]
                )[0]
                entry_span.set_attribute("ab_test.test_id",   test_id)
                entry_span.set_attribute("ab_test.variant",   variant)
                ab_assignments.add(1, attributes={"ab_test.test_id": test_id,
                                                   "ab_test.variant": variant})
                abtesting.logger.info(
                    f"AB assignment: test={test_id} variant={variant} entity={entity_id}",
                    extra={"request.id": request_id, "ab_test.test_id": test_id,
                           "ab_test.variant": variant, "entity.id": entity_id,
                           "model.name": model["name"]}
                )
            return variant, test_id, inject_traceparent(entry_span)


def svc_feature_store(request_id: str, model: dict, entity_id: str,
                       parent_tp: str, force_stale: bool = False) -> tuple:
    """Retrieve or compute features for inference."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "http.client.feature_store", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "feature-store",
                    "http.url": "http://feature-store/api/v2/features/batch",
                    "request.id": request_id, "model.name": model["name"],
                    "feature.count": model["feature_count"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with features.tracer.start_as_current_span(
            "feature.fetch_batch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v2/features/batch",
                        "request.id": request_id, "model.name": model["name"],
                        "feature.count": model["feature_count"],
                        "feature.store_backend": "redis+offline-parquet",
                        "feature.online_pct": 0.75, "feature.offline_pct": 0.25,
                        "entity.id": entity_id}
        ) as entry_span:
            time.sleep(random.uniform(0.03, 0.10))

            staleness_secs = random.randint(0, 7200) if force_stale else random.randint(0, 3599)
            is_stale       = staleness_secs > 3600

            entry_span.set_attribute("feature.staleness_seconds",  staleness_secs)
            entry_span.set_attribute("feature.is_stale",           is_stale)
            entry_span.set_attribute("feature.count_returned",     model["feature_count"])
            entry_span.set_attribute("feature.online_hits",        int(model["feature_count"] * 0.75))
            entry_span.set_attribute("feature.offline_hits",       int(model["feature_count"] * 0.25))

            dur_ms = (time.time() - t0) * 1000
            feat_fetches.add(1, attributes={"model.name": model["name"]})
            feat_latency.record(dur_ms, attributes={"model.name": model["name"]})
            feat_count.record(model["feature_count"], attributes={"model.name": model["name"]})

            if is_stale:
                feat_stale.add(1, attributes={"model.name": model["name"]})
                features.logger.warning(
                    f"stale features: {staleness_secs}s old for entity {entity_id}",
                    extra={"request.id": request_id, "model.name": model["name"],
                           "entity.id": entity_id, "feature.staleness_seconds": staleness_secs,
                           "feature.is_stale": True, "feature.stale_threshold_seconds": 3600}
                )
            else:
                features.logger.info(
                    f"features fetched: {model['feature_count']} features ({staleness_secs}s old)",
                    extra={"request.id": request_id, "model.name": model["name"],
                           "entity.id": entity_id, "feature.staleness_seconds": staleness_secs,
                           "feature.count_returned": model["feature_count"]}
                )
            return model["feature_count"], staleness_secs, is_stale, inject_traceparent(entry_span)


def svc_model_registry(request_id: str, model: dict, parent_tp: str,
                         force_mismatch: bool = False) -> tuple:
    """Load model metadata and check version."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "http.client.model_registry", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "GET", "net.peer.name": "model-registry",
                    "http.url": f"http://model-registry/api/v1/models/{model['name']}/metadata",
                    "request.id": request_id, "model.name": model["name"],
                    "model.version": model["version"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with registry.tracer.start_as_current_span(
            "registry.get_model_metadata", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "GET",
                        "http.route": "/api/v1/models/{name}/metadata",
                        "request.id": request_id, "model.name": model["name"],
                        "model.version": model["version"],
                        "model.framework": model["framework"],
                        "model.task": model["task"],
                        "registry.backend": "mlflow+s3"}
        ) as entry_span:
            time.sleep(random.uniform(0.01, 0.04))

            latest_version = model["latest"]
            has_newer      = force_mismatch and latest_version != model["version"]
            entry_span.set_attribute("model.current_version",  model["version"])
            entry_span.set_attribute("model.latest_version",   latest_version)
            entry_span.set_attribute("model.version_is_latest", not has_newer)
            entry_span.set_attribute("model.feature_count",    model["feature_count"])
            entry_span.set_attribute("model.gpu_required",     model["gpu_required"])

            dur_ms = (time.time() - t0) * 1000

            if has_newer:
                registry.logger.warning(
                    f"model version mismatch: running {model['version']} but {latest_version} available",
                    extra={"request.id": request_id, "model.name": model["name"],
                           "model.current_version": model["version"],
                           "model.latest_version": latest_version,
                           "model.rollout_triggered": True}
                )
                entry_span.set_attribute("model.rollout_triggered", True)
            else:
                registry.logger.info(
                    f"model metadata: {model['name']} v{model['version']} (latest)",
                    extra={"request.id": request_id, "model.name": model["name"],
                           "model.version": model["version"], "model.task": model["task"],
                           "model.framework": model["framework"]}
                )
            return latest_version, has_newer, inject_traceparent(entry_span)


def svc_serving_engine(request_id: str, model: dict, feature_count: int,
                        ab_variant: str, parent_tp: str,
                        cold_start: bool = False,
                        gpu_oom: bool = False) -> tuple:
    """Execute model inference on serving cluster."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "http.client.serving_engine", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "serving-engine",
                    "http.url": "http://serving-engine/api/v2/predict",
                    "request.id": request_id, "model.name": model["name"],
                    "model.version": model["version"], "ab_test.variant": ab_variant}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with serving.tracer.start_as_current_span(
            "serving.predict", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v2/predict",
                        "request.id": request_id, "model.name": model["name"],
                        "model.version": model["version"], "model.framework": model["framework"],
                        "model.task": model["task"], "feature.count": feature_count,
                        "ab_test.variant": ab_variant,
                        "serving.cluster": "gpu-cluster-a100" if model["gpu_required"] else "cpu-cluster-c6i",
                        "serving.batching": True, "serving.batch_size": random.randint(1, 32)}
        ) as entry_span:
            srv_requests.add(1, attributes={"model.name": model["name"],
                                             "model.framework": model["framework"]})

            # Cold start: load model into memory
            if cold_start:
                with serving.tracer.start_as_current_span(
                    "serving.model_load", kind=SpanKind.INTERNAL,
                    attributes={"model.name": model["name"], "model.version": model["version"],
                                "model.framework": model["framework"],
                                "serving.load_source": "s3://model-artifacts/"}
                ) as load_span:
                    load_time = random.uniform(2.5, 8.0)
                    time.sleep(load_time)
                    load_span.set_attribute("serving.load_duration_ms", round(load_time * 1000, 2))
                    srv_cold_start.add(1, attributes={"model.name": model["name"]})
                    entry_span.add_event("inference.model.loaded", {
                        "model.version": model["version"],
                        "model.framework": model["framework"],
                        "serving.load_duration_ms": round(load_time * 1000, 2),
                    })
                    serving.logger.warning(
                        f"cold start: loaded {model['name']} in {load_time:.1f}s",
                        extra={"request.id": request_id, "model.name": model["name"],
                               "serving.load_duration_ms": round(load_time * 1000, 2),
                               "serving.cold_start": True}
                    )

            # GPU OOM: failover to CPU
            if gpu_oom and model["gpu_required"]:
                gpu_mem = random.randint(38000, 42000)  # near 40GB A100 limit
                entry_span.set_attribute("gpu.memory_used_mb",  gpu_mem)
                entry_span.set_attribute("gpu.memory_limit_mb", 40960)
                gpu_mem_used.record(gpu_mem, attributes={"model.name": model["name"]})

                err = Exception(f"CUDAOutOfMemoryError: tried to allocate 2.50 GiB "
                                f"with only {40960 - gpu_mem} MiB free on gpu:0")
                entry_span.record_exception(err)
                entry_span.set_attribute("serving.failover_to_cpu", True)
                srv_gpu_oom.add(1, attributes={"model.name": model["name"]})
                serving.logger.error(
                    f"GPU OOM: failing over to CPU inference for {model['name']}",
                    extra={"request.id": request_id, "model.name": model["name"],
                           "gpu.memory_used_mb": gpu_mem, "serving.failover_to_cpu": True}
                )
                # CPU fallback
                time.sleep(random.uniform(0.5, 1.5))  # CPU is slower
                entry_span.set_attribute("serving.device", "cpu-fallback")
            else:
                time.sleep(random.uniform(0.05, 0.30))
                if model["gpu_required"]:
                    gpu_mem = random.randint(8000, 30000)
                    entry_span.set_attribute("gpu.memory_used_mb", gpu_mem)
                    gpu_mem_used.record(gpu_mem, attributes={"model.name": model["name"]})
                entry_span.set_attribute("serving.device", "gpu" if model["gpu_required"] else "cpu")

            dur_ms = (time.time() - t0) * 1000
            prediction_class = random.choice(PREDICTION_CLASSES.get(model["task"], ["value"]))
            confidence       = round(random.uniform(0.55, 0.99), 4)

            entry_span.add_event("inference.preprocessing.complete", {
                "features.count": feature_count,
                "model.framework": model["framework"],
            })
            entry_span.add_event("inference.prediction.complete", {
                "inference.latency_ms": round(dur_ms, 1),
                "prediction.class": prediction_class,
                "prediction.confidence": confidence,
            })

            entry_span.set_attribute("inference.latency_ms",      round(dur_ms, 2))
            entry_span.set_attribute("prediction.class",          prediction_class)
            entry_span.set_attribute("prediction.confidence",     confidence)
            entry_span.set_attribute("model.name",                model["name"])
            entry_span.set_attribute("model.version",             model["version"])

            srv_latency.record(dur_ms, attributes={"model.name": model["name"],
                                                    "model.framework": model["framework"],
                                                    "serving.device": "gpu" if model["gpu_required"] else "cpu"})

            serving.logger.info(
                f"inference complete: {model['name']} → {prediction_class} ({confidence:.3f}) in {dur_ms:.0f}ms",
                extra={"request.id": request_id, "model.name": model["name"],
                       "model.version": model["version"], "prediction.class": prediction_class,
                       "prediction.confidence": confidence, "inference.latency_ms": round(dur_ms, 2),
                       "ab_test.variant": ab_variant}
            )
            return prediction_class, confidence, inject_traceparent(entry_span)


def svc_explainability(request_id: str, model: dict, prediction_class: str,
                         confidence: float, parent_tp: str) -> None:
    """Compute SHAP values for regulated industry requests."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with gateway.tracer.start_as_current_span(
        "http.client.explainability", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "explainability-service",
                    "http.url": "http://explainability-service/api/v1/explain",
                    "request.id": request_id, "model.name": model["name"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with explain.tracer.start_as_current_span(
            "explain.compute_shap", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/explain",
                        "request.id": request_id, "model.name": model["name"],
                        "model.version": model["version"],
                        "explainability.method": "shap-treexplainer",
                        "explainability.top_k_features": 10,
                        "prediction.class": prediction_class,
                        "prediction.confidence": confidence}
        ) as entry_span:
            time.sleep(random.uniform(0.10, 0.35))  # SHAP is expensive

            shap_values = {f"feature_{i}": round(random.uniform(-1.5, 1.5), 4)
                           for i in range(10)}
            top_feature = max(shap_values, key=lambda k: abs(shap_values[k]))

            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("explainability.top_feature",     top_feature)
            entry_span.set_attribute("explainability.top_shap_value",  shap_values[top_feature])
            entry_span.set_attribute("explainability.shap_sum",        round(sum(shap_values.values()), 4))
            entry_span.set_attribute("explainability.duration_ms",     round(dur_ms, 2))

            exp_requests.add(1, attributes={"model.name": model["name"]})
            exp_latency.record(dur_ms, attributes={"explainability.method": "shap-treexplainer"})

            explain.logger.info(
                f"SHAP computed: top feature={top_feature} ({shap_values[top_feature]:+.4f})",
                extra={"request.id": request_id, "model.name": model["name"],
                       "explainability.top_feature": top_feature,
                       "explainability.duration_ms": round(dur_ms, 2),
                       "prediction.class": prediction_class}
            )


def svc_cache_set(request_id: str, model: dict, entity_id: str,
                   prediction: dict, parent_tp: str) -> None:
    """Write inference result back to cache."""
    parent_ctx = extract_context(parent_tp)
    cache_key  = f"infer:{model['name']}:{entity_id}:{model['version']}"

    with gateway.tracer.start_as_current_span(
        "redis.client.cache_set", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"db.system": "redis", "net.peer.name": "result-cache",
                    "db.operation": "SETEX", "cache.key": cache_key,
                    "cache.ttl_seconds": 300}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with cache.tracer.start_as_current_span(
            "cache.set", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"db.system": "redis", "db.operation": "SETEX",
                        "cache.key": cache_key, "cache.ttl_seconds": 300,
                        "model.name": model["name"]}
        ) as entry_span:
            time.sleep(random.uniform(0.002, 0.008))
            cache_sets.add(1, attributes={"model.name": model["name"]})
            entry_span.set_attribute("cache.stored", True)
            cache.logger.info(
                f"cache SET: {cache_key} (TTL=300s)",
                extra={"request.id": request_id, "cache.key": cache_key,
                       "model.name": model["name"], "cache.ttl_seconds": 300}
            )


# ── Main scenario runner ───────────────────────────────────────────────────────

def run_inference_scenario(scenario: str, model: dict, entity_id: str,
                            industry: str, needs_explanation: bool):
    """Execute a full inference request flow."""
    request_id = f"INF-{uuid.uuid4().hex[:12].upper()}"
    t_start    = time.time()

    is_cache_hit     = scenario == "cache_hit"
    is_cold_start    = scenario == "cold_start"
    force_stale      = scenario == "feature_stale"
    force_gpu_oom    = scenario == "gpu_oom"
    force_mismatch   = scenario == "version_mismatch"

    print(f"\n  [{scenario}] model={model['name']} v{model['version']} "
          f"entity={entity_id} industry={industry} explain={needs_explanation}")

    with gateway.tracer.start_as_current_span(
        "gateway.inference_request", kind=SpanKind.SERVER,
        attributes={"http.method": "POST", "http.route": "/api/v2/infer",
                    "request.id": request_id, "model.name": model["name"],
                    "model.version": model["version"], "model.task": model["task"],
                    "model.framework": model["framework"],
                    "entity.id": entity_id, "caller.industry": industry,
                    "explainability.requested": needs_explanation,
                    "scenario": scenario}
    ) as root_span:
        tp_root = inject_traceparent(root_span)
        gw_requests.add(1, attributes={"model.name": model["name"],
                                        "model.task": model["task"]})

        gateway.logger.info(
            f"inference request: {request_id} model={model['name']} industry={industry}",
            extra={"request.id": request_id, "model.name": model["name"],
                   "model.task": model["task"], "caller.industry": industry,
                   "explainability.requested": needs_explanation}
        )

        # Step 1: check cache
        hit, cached_result, tp = svc_result_cache(
            request_id, model, entity_id, tp_root, cache_hit=is_cache_hit)

        if hit:
            gw_cache_hits.add(1, attributes={"model.name": model["name"]})
            root_span.set_attribute("cache.hit",               True)
            root_span.set_attribute("prediction.class",        cached_result["class"])
            root_span.set_attribute("prediction.confidence",   cached_result["confidence"])
            dur_ms = (time.time() - t_start) * 1000
            gw_latency.record(dur_ms, attributes={"cache.hit": "true",
                                                   "model.name": model["name"]})
            gateway.logger.info(
                f"served from cache: {request_id} → {cached_result['class']} in {dur_ms:.0f}ms",
                extra={"request.id": request_id, "model.name": model["name"],
                       "cache.hit": True, "prediction.class": cached_result["class"],
                       "inference.latency_ms": round(dur_ms, 2)}
            )
            print(f"    ✅ Cache HIT: {cached_result['class']} "
                  f"({cached_result['confidence']:.3f}) in {dur_ms:.0f}ms")
            return True

        # Step 2: A/B test assignment
        ab_variant, test_id, tp = svc_ab_testing(request_id, model, entity_id, tp_root)

        # Step 3: feature store
        feature_count, staleness, is_stale, tp = svc_feature_store(
            request_id, model, entity_id, tp_root, force_stale=force_stale)

        if is_stale:
            root_span.set_attribute("feature.stale_warning", True)
            root_span.set_attribute("feature.staleness_seconds", staleness)

        # Step 4: model registry
        latest_ver, has_mismatch, tp = svc_model_registry(
            request_id, model, tp_root, force_mismatch=force_mismatch)

        if has_mismatch:
            root_span.set_attribute("model.version_mismatch", True)
            root_span.set_attribute("model.latest_version",   latest_ver)

        # Step 5: serving engine
        pred_class, confidence, tp = svc_serving_engine(
            request_id, model, feature_count, ab_variant, tp_root,
            cold_start=is_cold_start, gpu_oom=force_gpu_oom)

        # Step 6: explainability (regulated industry or explicitly requested)
        if needs_explanation or industry in REGULATED_INDUSTRIES:
            svc_explainability(request_id, model, pred_class, confidence, tp_root)
            root_span.set_attribute("explainability.computed", True)

        # Step 7: write result back to cache
        svc_cache_set(request_id, model, entity_id,
                       {"class": pred_class, "confidence": confidence}, tp_root)

        dur_ms = (time.time() - t_start) * 1000
        root_span.set_attribute("cache.hit",               False)
        root_span.set_attribute("prediction.class",        pred_class)
        root_span.set_attribute("prediction.confidence",   confidence)
        root_span.set_attribute("inference.latency_ms",    round(dur_ms, 2))
        root_span.set_attribute("ab_test.variant",         ab_variant)
        root_span.set_attribute("feature.staleness_seconds", staleness)

        gw_latency.record(dur_ms, attributes={"cache.hit": "false",
                                               "model.name": model["name"]})

        tags = []
        if is_stale:      tags.append("stale features")
        if has_mismatch:  tags.append("version mismatch")
        if is_cold_start: tags.append("cold start")
        if force_gpu_oom: tags.append("GPU OOM→CPU")
        suffix = f" [{', '.join(tags)}]" if tags else ""
        icon   = "⚠️" if tags else "✅"
        print(f"    {icon} Inference{suffix}: {pred_class} ({confidence:.3f}) in {dur_ms:.0f}ms "
              f"(variant={ab_variant})")
        return True


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print("  ML Inference Platform — Distributed Tracing Demo")
    print("  Services: inference-gateway → result-cache → ab-testing-service")
    print("            → feature-store → model-registry → serving-engine")
    print("            → explainability-service")
    print(f"{'='*70}")

    # 25 scenarios
    scenario_pool = (
        ["cache_hit"] * 14 +
        ["cache_miss"] * 5 +
        ["cold_start"] * 2 +
        ["feature_stale"] * 2 +
        ["gpu_oom"] * 1 +
        ["version_mismatch"] * 1
    )
    random.shuffle(scenario_pool)

    stats = {"cache_hit": 0, "cache_miss": 0, "cold_start": 0,
             "feature_stale": 0, "gpu_oom": 0, "version_mismatch": 0, "total": 0}

    for i, scenario in enumerate(scenario_pool):
        model         = random.choice(MODELS)
        entity_id     = f"ent_{uuid.uuid4().hex[:12]}"
        industry      = random.choice(CALLER_INDUSTRIES)
        needs_explain = industry in REGULATED_INDUSTRIES and random.random() < 0.5

        # GPU OOM only makes sense for GPU models
        if scenario == "gpu_oom" and not model["gpu_required"]:
            model = next(m for m in MODELS if m["gpu_required"])

        # Version mismatch needs a model that has a newer version
        if scenario == "version_mismatch":
            model = next((m for m in MODELS if m["version"] != m["latest"]), MODELS[1])

        print(f"\n{'─'*70}")
        print(f"  Scenario {i+1:02d}/25  [{scenario}]")
        run_inference_scenario(scenario, model, entity_id, industry, needs_explain)
        stats["total"] += 1
        stats[scenario] = stats.get(scenario, 0) + 1

        time.sleep(random.uniform(0.05, 0.2))

    print(f"\n{'='*70}")
    print("  Flushing all telemetry providers...")
    for svc in [gateway, cache, abtesting, features, registry, serving, explain]:
        svc.flush()

    print(f"\n  Results: {stats['total']} scenarios")
    print(f"    ✅ Cache hits:         {stats['cache_hit']}")
    print(f"    🔄 Full inference:     {stats['cache_miss']}")
    print(f"    🥶 Cold starts:        {stats['cold_start']}")
    print(f"    ⚠️  Stale features:    {stats['feature_stale']}")
    print(f"    💥 GPU OOM (CPU fb):  {stats['gpu_oom']}")
    print(f"    🔀 Version mismatch:  {stats['version_mismatch']}")

    print(f"\n  Kibana:")
    print(f"    Service Map → Observability → APM → Service Map")
    print(f"    Filter: inference-gateway (7 connected nodes expected)")
    print(f"\n  ES|QL query:")
    print(f'    FROM traces-apm*,logs-*')
    print(f'    | WHERE service.name IN ("inference-gateway","result-cache","ab-testing-service",')
    print(f'        "feature-store","model-registry","serving-engine","explainability-service")')
    print(f'    | SORT @timestamp DESC | LIMIT 100')
    print(f"{'='*70}\n")
