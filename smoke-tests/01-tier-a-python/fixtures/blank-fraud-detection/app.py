"""
Fraud Detection Service — FastAPI REST API

No observability. Run `Observe this project.` to add it.
"""

import os
import uuid
import random
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fraud Detection Service")

# ── In-memory store (simulates a real DB) ─────────────────────────────────────
_orders: dict = {}


# ── Request / Response models ─────────────────────────────────────────────────

class OrderItem(BaseModel):
    name: str
    price_usd: float
    qty: int = 1


class OrderRequest(BaseModel):
    customer_id: str
    customer_tier: str = "standard"  # standard / pro / enterprise
    items: List[OrderItem] = []


# ── Business logic ─────────────────────────────────────────────────────────────

def compute_fraud_score(customer_id: str, total_usd: float, tier: str) -> float:
    """Compute fraud risk score 0.0–1.0. Score > 0.75 = block the order."""
    base = random.uniform(0.0, 0.45)
    if total_usd > 1000:
        base += 0.15
    if tier == "enterprise":
        base -= 0.20  # enterprise customers have lower fraud baseline
    if tier == "free":
        base += 0.10  # free-tier customers get extra scrutiny
    return max(0.0, min(1.0, round(base, 4)))


def charge_payment(customer_id: str, amount_usd: float, method: str) -> dict:
    """Simulate external payment processor call."""
    if amount_usd > 50_000:
        return {"status": "declined", "reason": "amount_limit_exceeded"}
    return {
        "status": "charged",
        "charge_id": f"ch_{uuid.uuid4().hex[:12]}",
        "amount_usd": amount_usd,
        "method": method,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orders", status_code=201)
def create_order(body: OrderRequest):
    total_usd = sum(item.price_usd * item.qty for item in body.items)
    if total_usd <= 0:
        raise HTTPException(status_code=400, detail="order total must be > 0")

    fraud_score = compute_fraud_score(body.customer_id, total_usd, body.customer_tier)
    fraud_decision = "blocked" if fraud_score > 0.75 else "approved"

    if fraud_decision == "blocked":
        logger.warning("Order blocked: high fraud score",
                       extra={"customer_id": body.customer_id,
                              "fraud_score": fraud_score,
                              "total_usd": total_usd})
        raise HTTPException(status_code=402,
                            detail={"error": "order blocked", "reason": "fraud_check_failed",
                                    "fraud_score": fraud_score})

    payment = charge_payment(body.customer_id, total_usd, "card")
    if payment["status"] != "charged":
        raise HTTPException(status_code=402,
                            detail={"error": "payment failed",
                                    "reason": payment.get("reason")})

    order_id = str(uuid.uuid4())
    _orders[order_id] = {
        "order_id": order_id,
        "customer_id": body.customer_id,
        "customer_tier": body.customer_tier,
        "total_usd": total_usd,
        "fraud_score": fraud_score,
        "fraud_decision": fraud_decision,
        "payment_status": payment["status"],
        "charge_id": payment["charge_id"],
        "status": "confirmed",
    }

    logger.info("Order created",
                extra={"order_id": order_id, "customer_id": body.customer_id,
                       "total_usd": total_usd, "customer_tier": body.customer_tier})
    return _orders[order_id]


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = _orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.get("/orders")
def list_orders(customer_id: Optional[str] = None):
    orders = list(_orders.values())
    if customer_id:
        orders = [o for o in orders if o["customer_id"] == customer_id]
    return {"orders": orders, "count": len(orders)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
