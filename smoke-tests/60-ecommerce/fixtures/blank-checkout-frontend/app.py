"""
Checkout Frontend Service — Flask
E-Commerce Platform Core Service

No observability. Run `Observe this project.` to add OpenTelemetry.

This is the API gateway / frontend service in a multi-service e-commerce platform.
Downstream services:
  - product-catalog     (GET /products)
  - inventory-service   (GET /inventory/{sku})
  - pricing-engine      (POST /prices)
  - payment-service     (POST /payments)  -> fraud-detection, payment-processor
  - order-service       (POST /orders)    -> notification-service

Routes:
  GET  /health                  — liveness probe
  POST /checkout                — initiate checkout flow
  GET  /checkout/{session_id}   — get checkout session status
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

# ── In-memory store ────────────────────────────────────────────────────────────
sessions = {}


# ── Downstream service stubs ───────────────────────────────────────────────────

def call_product_catalog(product_ids: list) -> list:
    """GET /products — fetch product details."""
    time.sleep(random.uniform(0.010, 0.040))
    return [
        {"id": pid, "name": f"Product {pid}", "price_usd": round(random.uniform(9.99, 499.99), 2)}
        for pid in product_ids
    ]


def call_inventory(sku: str) -> dict:
    """GET /inventory/{sku} — check stock."""
    time.sleep(random.uniform(0.005, 0.025))
    return {"sku": sku, "in_stock": random.random() > 0.1, "qty": random.randint(0, 200)}


def call_pricing_engine(product_ids: list, customer_tier: str) -> dict:
    """POST /prices — compute tier-based pricing."""
    time.sleep(random.uniform(0.020, 0.060))
    if random.random() < 0.05:  # 5% timeout
        raise TimeoutError("pricing-engine: timeout after 60ms")
    discount = {"enterprise": 0.15, "pro": 0.05, "free": 0.0}.get(customer_tier, 0.0)
    return {"discount_pct": discount * 100}


def call_payment_service(amount_usd: float, customer_id: str, fraud_score: float) -> dict:
    """POST /payments — charge customer, includes fraud check."""
    time.sleep(random.uniform(0.080, 0.200))
    if fraud_score > 0.85:
        return {"status": "blocked", "reason": "fraud_score_too_high"}
    if random.random() < 0.10:  # 10% card decline
        return {"status": "declined", "reason": "card_declined"}
    charge_id = f"ch_{uuid.uuid4().hex[:16]}"
    return {"status": "charged", "charge_id": charge_id, "amount_usd": amount_usd}


def call_order_service(session_id: str, customer_id: str, payment: dict, items: list) -> dict:
    """POST /orders — create order record."""
    time.sleep(random.uniform(0.015, 0.050))
    if random.random() < 0.02:  # 2% DB failure
        raise RuntimeError("order-service: DB connection lost")
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    return {"order_id": order_id, "status": "confirmed"}


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/checkout", methods=["POST"])
def checkout():
    body = request.get_json(force=True) or {}
    customer_id   = body.get("customer_id", "anon")
    customer_tier = body.get("customer_tier", "free")
    items         = body.get("items", [])

    if not items:
        return jsonify({"error": "items required"}), 400

    session_id = str(uuid.uuid4())
    product_ids = [item.get("product_id") for item in items if item.get("product_id")]

    try:
        # Step 1: Fetch products
        products = call_product_catalog(product_ids)

        # Step 2: Check inventory
        for product in products:
            inv = call_inventory(product["id"])
            if not inv["in_stock"]:
                logger.warning("Item out of stock: %s", product["id"])
                return jsonify({
                    "error": "item_out_of_stock",
                    "product_id": product["id"],
                }), 422

        # Step 3: Compute pricing
        try:
            pricing = call_pricing_engine(product_ids, customer_tier)
        except TimeoutError:
            logger.warning("Pricing engine timeout — proceeding without discount")
            pricing = {"discount_pct": 0.0}

        # Step 4: Calculate total
        total_usd = sum(p["price_usd"] for p in products)
        discount  = total_usd * (pricing["discount_pct"] / 100)
        charge_amount = total_usd - discount

        # Step 5: Fraud score (simplified)
        fraud_score = random.uniform(0.0, 0.5)
        if customer_tier == "enterprise":
            fraud_score *= 0.5

        # Step 6: Payment
        payment = call_payment_service(charge_amount, customer_id, fraud_score)
        if payment["status"] != "charged":
            return jsonify({"error": payment["status"], "reason": payment.get("reason")}), 402

        # Step 7: Create order
        order = call_order_service(session_id, customer_id, payment, items)

        sessions[session_id] = {
            "session_id":  session_id,
            "order_id":    order["order_id"],
            "customer_id": customer_id,
            "total_usd":   charge_amount,
            "status":      "completed",
        }

        logger.info("Checkout completed: session=%s order=%s total=$%.2f",
                    session_id, order["order_id"], charge_amount)

        return jsonify(sessions[session_id]), 201

    except RuntimeError as e:
        logger.error("Checkout failed: %s", e)
        sessions[session_id] = {"session_id": session_id, "status": "failed", "error": str(e)}
        return jsonify({"error": "checkout_failed", "detail": str(e)}), 500


@app.route("/checkout/<session_id>")
def get_session(session_id):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404
    return jsonify(session)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6000))
    app.run(host="0.0.0.0", port=port, debug=False)
