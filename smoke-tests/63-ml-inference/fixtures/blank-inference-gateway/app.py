"""
Inference Gateway — ML Inference Platform (Flask)

No observability. Run `Observe this project.` to add OpenTelemetry.

This is the API gateway for an ML inference platform. Downstream services:
  - result-cache        — Redis cache for inference results
  - ab-testing-service  — model variant selection
  - feature-store       — feature vector retrieval
  - model-registry      — model metadata & version resolution
  - serving-engine      — GPU inference execution
  - explainability-svc  — SHAP/LIME explanations

Routes:
  GET  /health                 — liveness probe
  POST /predict                — run inference
  GET  /predict/{request_id}   — get prediction result
"""

import os
import uuid
import random
import logging
import time
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
results = {}


def call_result_cache(cache_key: str) -> dict | None:
    """Check Redis cache for pre-computed result."""
    time.sleep(random.uniform(0.001, 0.005))
    # 55% cache hit rate
    if random.random() < 0.55:
        return {
            "prediction": round(random.uniform(0.0, 1.0), 4),
            "model_version": "v2.3.1",
            "cached": True,
        }
    return None


def call_ab_testing(model_id: str) -> dict:
    """Select model variant via A/B test."""
    time.sleep(random.uniform(0.003, 0.010))
    variants = ["v2.3.1", "v2.4.0-canary", "v2.2.5-stable"]
    return {"variant": random.choice(variants), "experiment": "model-upgrade-2024q1"}


def call_feature_store(entity_id: str) -> dict:
    """Retrieve feature vector for entity."""
    time.sleep(random.uniform(0.010, 0.040))
    # 8% staleness warning
    stale = random.random() < 0.08
    features = {f"feat_{i}": round(random.uniform(-1.0, 1.0), 4) for i in range(10)}
    return {"ok": True, "features": features, "stale": stale, "age_s": random.randint(0, 3600)}


def call_model_registry(model_id: str, variant: str) -> dict:
    """Resolve model version and get serving config."""
    time.sleep(random.uniform(0.005, 0.015))
    # 2% version mismatch
    if random.random() < 0.02:
        raise ValueError(f"model-registry: version mismatch for {model_id}@{variant}")
    return {
        "model_path": f"s3://models/{model_id}/{variant}/model.pb",
        "hardware":   "gpu",
        "batch_size": 32,
    }


def call_serving_engine(features: dict, model_config: dict) -> dict:
    """Execute GPU inference."""
    # 5% GPU OOM fallback to CPU
    if random.random() < 0.05:
        logger.warning("GPU OOM — falling back to CPU serving")
        time.sleep(random.uniform(0.200, 0.500))  # CPU is slower
        hardware = "cpu"
    else:
        time.sleep(random.uniform(0.020, 0.080))
        hardware = model_config.get("hardware", "gpu")

    prediction = round(random.uniform(0.0, 1.0), 4)
    return {
        "prediction":    prediction,
        "confidence":    round(random.uniform(0.7, 0.99), 4),
        "hardware_used": hardware,
        "latency_ms":    round(random.uniform(20, 500), 1),
    }


def call_explainability(features: dict, prediction: float) -> dict:
    """Generate SHAP explanations (async, best-effort)."""
    time.sleep(random.uniform(0.050, 0.200))
    top_features = sorted(features.keys(), key=lambda _: random.random())[:3]
    return {"top_features": top_features, "explanation_type": "shap"}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/predict", methods=["POST"])
def predict():
    body      = request.get_json(force=True) or {}
    model_id  = body.get("model_id", "churn-predictor")
    entity_id = body.get("entity_id", str(uuid.uuid4()))
    explain   = body.get("explain", False)

    if not model_id:
        return jsonify({"error": "model_id required"}), 400

    request_id = f"req_{uuid.uuid4().hex[:12]}"
    cache_key  = f"{model_id}:{entity_id}"

    # Step 1: Check cache
    cached_result = call_result_cache(cache_key)
    if cached_result:
        cached_result["request_id"] = request_id
        results[request_id] = cached_result
        logger.info("Cache hit: request=%s model=%s entity=%s",
                    request_id, model_id, entity_id)
        return jsonify(cached_result), 200

    # Step 2: A/B test — select variant
    ab_result = call_ab_testing(model_id)
    variant   = ab_result["variant"]

    # Step 3: Fetch features
    feature_result = call_feature_store(entity_id)
    if feature_result.get("stale"):
        logger.warning("Stale features for entity %s (age=%ds)",
                       entity_id, feature_result.get("age_s", 0))
    features = feature_result["features"]

    # Step 4: Resolve model
    try:
        model_config = call_model_registry(model_id, variant)
    except ValueError as e:
        logger.error("Model registry error: %s", e)
        return jsonify({"error": "model_version_mismatch", "detail": str(e)}), 503

    # Step 5: Run inference
    inference = call_serving_engine(features, model_config)

    # Step 6: Explainability (optional)
    explanation = None
    if explain:
        explanation = call_explainability(features, inference["prediction"])

    result = {
        "request_id":    request_id,
        "model_id":      model_id,
        "model_version": variant,
        "entity_id":     entity_id,
        "prediction":    inference["prediction"],
        "confidence":    inference["confidence"],
        "hardware":      inference["hardware_used"],
        "latency_ms":    inference["latency_ms"],
        "cached":        False,
        **({"explanation": explanation} if explanation else {}),
    }
    results[request_id] = result

    logger.info("Prediction: request=%s model=%s prediction=%.4f latency=%.1fms",
                request_id, model_id, inference["prediction"], inference["latency_ms"])
    return jsonify(result), 200


@app.route("/predict/<request_id>")
def get_result(request_id):
    result = results.get(request_id)
    if not result:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6003))
    app.run(host="0.0.0.0", port=port, debug=False)
