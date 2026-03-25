"""
Tier A — Python FastAPI with native EDOT auto-instrumentation.

EDOT auto-instruments FastAPI, SQLAlchemy, httpx, and more — zero manual spans needed.
Run with:
    edot-bootstrap -- uvicorn main:app --port 8000

Or via Docker:
    docker compose up
"""

import os
import random
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="EDOT Test — FastAPI (Tier A)")


class Order(BaseModel):
    customer_id: str
    item: str
    amount: float
    customer_tier: str = "free"


@app.get("/health")
def health():
    return {"status": "ok", "service": os.environ.get("OTEL_SERVICE_NAME", "fastapi-tier-a")}


@app.post("/orders")
def create_order(order: Order):
    """
    Simulates order creation. EDOT auto-instruments this HTTP handler.
    Add business enrichment here (Phase 3) by adding span attributes.
    """
    from opentelemetry import trace
    span = trace.get_current_span()

    # Phase 3: business enrichment — added on top of EDOT auto-instrumentation
    span.set_attribute("order.customer_id", order.customer_id)
    span.set_attribute("order.amount_usd", order.amount)
    span.set_attribute("order.item", order.item)
    span.set_attribute("customer.tier", order.customer_tier)

    # Simulate fraud check
    fraud_score = random.uniform(0.0, 1.0)
    span.set_attribute("fraud.score", round(fraud_score, 3))

    if fraud_score > 0.85:
        span.set_attribute("fraud.decision", "blocked")
        raise HTTPException(status_code=402, detail="Order blocked by fraud check")

    span.set_attribute("fraud.decision", "approved")

    order_id = f"ORD-{random.randint(10000, 99999)}"
    span.set_attribute("order.id", order_id)
    return {"order_id": order_id, "status": "confirmed"}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    from opentelemetry import trace
    span = trace.get_current_span()
    span.set_attribute("order.id", order_id)
    # Simulate occasional 404
    if random.random() < 0.1:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order_id": order_id, "status": "shipped", "amount_usd": random.uniform(10, 500)}
