"""
Order Management Service — Flask REST API

No observability. Run `Observe this project.` to add it.
"""

import os
import uuid
import random
import logging

from flask import Flask, jsonify, request
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# StaticPool ensures all connections share the same in-memory SQLite database.
# Required for sqlite:///:memory: so the CREATE TABLE and subsequent queries
# hit the same database object.
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)

# ── Bootstrap DB ──────────────────────────────────────────────────────────────
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS orders (
            id          TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            customer_tier TEXT NOT NULL DEFAULT 'standard',
            items_json  TEXT,
            total_usd   REAL NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            fraud_score REAL
        )
    """))
    conn.commit()

# ── Payment gateway (external HTTP call) ──────────────────────────────────────
PAYMENT_TIMEOUT_MS = 3000  # SLO: p99 < 3s

def call_payment_gateway(amount_usd: float, customer_id: str) -> dict:
    """Call external payment gateway. Returns charge result."""
    # In prod this calls https://pay.internal/charge
    # For local dev we simulate it
    if amount_usd > 10_000:
        return {"status": "declined", "reason": "limit_exceeded"}
    return {"status": "charged", "charge_id": f"ch_{uuid.uuid4().hex[:12]}"}


def compute_fraud_score(customer_id: str, amount_usd: float, tier: str) -> float:
    """Compute fraud risk score 0.0–1.0. > 0.7 = block order."""
    base = random.uniform(0.0, 0.4)
    if amount_usd > 500:
        base += 0.1
    if tier == "enterprise":
        base -= 0.15  # enterprise customers get more trust
    return max(0.0, min(1.0, base))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/orders", methods=["POST"])
def create_order():
    body = request.get_json(force=True)
    customer_id = body.get("customer_id", "anon")
    customer_tier = body.get("customer_tier", "standard")
    items = body.get("items", [])
    total_usd = sum(i.get("price_usd", 0) * i.get("qty", 1) for i in items)

    if total_usd <= 0:
        return jsonify({"error": "order total must be > 0"}), 400

    # Fraud check
    fraud_score = compute_fraud_score(customer_id, total_usd, customer_tier)
    if fraud_score > 0.7:
        logger.warning("Order blocked: high fraud score", extra={
            "customer_id": customer_id, "fraud_score": fraud_score
        })
        return jsonify({"error": "order blocked", "reason": "fraud_check_failed"}), 402

    # Payment
    payment = call_payment_gateway(total_usd, customer_id)
    if payment["status"] != "charged":
        return jsonify({"error": "payment failed", "reason": payment.get("reason")}), 402

    # Persist
    order_id = str(uuid.uuid4())
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO orders (id, customer_id, customer_tier, total_usd, status, fraud_score)
            VALUES (:id, :cid, :tier, :total, 'confirmed', :fraud)
        """), {"id": order_id, "cid": customer_id, "tier": customer_tier,
               "total": total_usd, "fraud": fraud_score})
        conn.commit()

    logger.info("Order created", extra={
        "order_id": order_id, "customer_id": customer_id, "total_usd": total_usd
    })
    return jsonify({
        "order_id": order_id,
        "status": "confirmed",
        "total_usd": total_usd,
        "charge_id": payment["charge_id"],
    }), 201


@app.route("/orders/<order_id>")
def get_order(order_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, customer_id, customer_tier, total_usd, status FROM orders WHERE id = :id"),
            {"id": order_id}
        ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "order_id": row[0], "customer_id": row[1],
        "customer_tier": row[2], "total_usd": row[3], "status": row[4],
    })


@app.route("/orders/<order_id>/fulfil", methods=["POST"])
def fulfil_order(order_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("UPDATE orders SET status='fulfilled' WHERE id = :id AND status='confirmed'"),
            {"id": order_id}
        )
        conn.commit()
    if result.rowcount == 0:
        return jsonify({"error": "order not found or not in confirmed state"}), 404
    return jsonify({"order_id": order_id, "status": "fulfilled"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
