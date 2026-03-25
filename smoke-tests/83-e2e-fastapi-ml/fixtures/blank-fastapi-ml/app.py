"""
ML Inference Service — FastAPI

No observability. Run `Observe this project.` to add it.

A machine learning inference API that accepts feature vectors and returns
predictions. Uses mock models that simulate sklearn-style classifiers.
This is a latency-sensitive service: p99 inference must be < 200ms.
"""

import os
import random
import logging
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ML Inference Service", version="1.0.0")

# ── Mock model registry ────────────────────────────────────────────────────────
# In production these would be loaded from S3 / MLflow Model Registry

INFERENCE_TIMEOUT_MS = 200  # SLO: p99 < 200ms

MODELS = {
    "iris-classifier-v1": {
        "classes":     ["setosa", "versicolor", "virginica"],
        "description": "Iris species classifier",
        "version":     "1.0.0",
    },
    "fraud-detector-v2": {
        "classes":     ["legitimate", "fraudulent"],
        "description": "Transaction fraud detection",
        "version":     "2.0.0",
    },
    "sentiment-v3": {
        "classes":     ["positive", "negative", "neutral"],
        "description": "Product review sentiment analysis",
        "version":     "3.0.0",
    },
}


class PredictRequest(BaseModel):
    features:   list[float]
    model_name: str = "iris-classifier-v1"
    customer_id: str = "anon"


class PredictResponse(BaseModel):
    prediction:    str
    confidence:    float
    model_name:    str
    inference_ms:  float


class ModelInfo(BaseModel):
    name:        str
    description: str
    version:     str
    classes:     list[str]


def _mock_predict(model_name: str, features: list[float]) -> tuple[str, float]:
    """Simulate model inference. Returns (prediction_class, confidence)."""
    model = MODELS[model_name]
    t0    = time.time()
    # Simulate variable inference latency (10-80ms)
    time.sleep(random.uniform(0.010, 0.080))
    prediction = random.choice(model["classes"])
    confidence = round(random.uniform(0.70, 0.99), 4)
    logger.info(f"model={model_name} prediction={prediction} confidence={confidence}")
    return prediction, confidence


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/models", response_model=list[ModelInfo])
def list_models():
    return [
        ModelInfo(name=name, **{k: v for k, v in info.items() if k != "name"})
        for name, info in MODELS.items()
    ]


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if req.model_name not in MODELS:
        raise HTTPException(status_code=404,
                            detail=f"Model '{req.model_name}' not found. "
                                   f"Available: {list(MODELS.keys())}")

    if not req.features:
        raise HTTPException(status_code=400, detail="features list cannot be empty")

    t0 = time.time()
    prediction, confidence = _mock_predict(req.model_name, req.features)
    inference_ms = round((time.time() - t0) * 1000, 2)

    return PredictResponse(
        prediction   = prediction,
        confidence   = confidence,
        model_name   = req.model_name,
        inference_ms = inference_ms,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
