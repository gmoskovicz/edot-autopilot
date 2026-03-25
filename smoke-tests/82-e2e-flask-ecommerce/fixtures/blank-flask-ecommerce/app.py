"""
E-Commerce API — Flask + SQLAlchemy

No observability. Run `Observe this project.` to add it.

A simple e-commerce REST API that supports a product catalog, shopping cart
management, and order checkout. Uses SQLite for storage.
"""

import os
import uuid
import logging

from flask import Flask, jsonify, request
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)

# ── Bootstrap DB ───────────────────────────────────────────────────────────────
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS products (
            id      TEXT PRIMARY KEY,
            name    TEXT NOT NULL,
            price   REAL NOT NULL,
            stock   INTEGER NOT NULL DEFAULT 0
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS carts (
            session_id  TEXT NOT NULL,
            product_id  TEXT NOT NULL,
            quantity    INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (session_id, product_id)
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS orders (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL,
            total       REAL NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending'
        )
    """))
    conn.commit()


# ── Product routes ─────────────────────────────────────────────────────────────

@app.route("/products", methods=["POST"])
def create_product():
    body = request.get_json(force=True)
    product_id = str(uuid.uuid4())
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO products (id, name, price, stock) VALUES (:id, :name, :price, :stock)"
        ), {"id": product_id, "name": body["name"],
            "price": body["price"], "stock": body.get("stock", 100)})
        conn.commit()
    return jsonify({"product_id": product_id, "name": body["name"]}), 201


@app.route("/products", methods=["GET"])
def list_products():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name, price, stock FROM products")).fetchall()
    return jsonify([{"id": r[0], "name": r[1], "price": r[2], "stock": r[3]} for r in rows])


@app.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, name, price, stock FROM products WHERE id = :id"),
            {"id": product_id}
        ).fetchone()
    if not row:
        return jsonify({"error": "product not found"}), 404
    return jsonify({"id": row[0], "name": row[1], "price": row[2], "stock": row[3]})


# ── Cart routes ────────────────────────────────────────────────────────────────

@app.route("/cart", methods=["POST"])
def add_to_cart():
    body       = request.get_json(force=True)
    session_id = body.get("session_id", str(uuid.uuid4()))
    product_id = body["product_id"]
    quantity   = body.get("quantity", 1)
    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT quantity FROM carts WHERE session_id = :s AND product_id = :p"),
            {"s": session_id, "p": product_id}
        ).fetchone()
        if existing:
            conn.execute(
                text("UPDATE carts SET quantity = :q WHERE session_id = :s AND product_id = :p"),
                {"q": existing[0] + quantity, "s": session_id, "p": product_id}
            )
        else:
            conn.execute(
                text("INSERT INTO carts (session_id, product_id, quantity) VALUES (:s, :p, :q)"),
                {"s": session_id, "p": product_id, "q": quantity}
            )
        conn.commit()
    return jsonify({"session_id": session_id, "product_id": product_id, "quantity": quantity})


@app.route("/cart/<session_id>", methods=["GET"])
def get_cart(session_id):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT product_id, quantity FROM carts WHERE session_id = :s"),
            {"s": session_id}
        ).fetchall()
    return jsonify({"session_id": session_id,
                    "items": [{"product_id": r[0], "quantity": r[1]} for r in rows]})


# ── Checkout routes ────────────────────────────────────────────────────────────

@app.route("/checkout", methods=["POST"])
def checkout():
    body       = request.get_json(force=True)
    session_id = body.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    with engine.connect() as conn:
        cart_items = conn.execute(
            text("SELECT c.product_id, c.quantity, p.price FROM carts c "
                 "JOIN products p ON c.product_id = p.id "
                 "WHERE c.session_id = :s"),
            {"s": session_id}
        ).fetchall()

    if not cart_items:
        return jsonify({"error": "cart is empty"}), 400

    total    = sum(row[1] * row[2] for row in cart_items)
    order_id = str(uuid.uuid4())

    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO orders (id, session_id, total, status) VALUES (:id, :s, :t, 'confirmed')"),
            {"id": order_id, "s": session_id, "t": total}
        )
        conn.execute(
            text("DELETE FROM carts WHERE session_id = :s"),
            {"s": session_id}
        )
        conn.commit()

    logger.info(f"Order confirmed: {order_id} total={total:.2f}")
    return jsonify({"order_id": order_id, "total": total, "status": "confirmed"}), 201


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, session_id, total, status FROM orders WHERE id = :id"),
            {"id": order_id}
        ).fetchone()
    if not row:
        return jsonify({"error": "order not found"}), 404
    return jsonify({"id": row[0], "session_id": row[1], "total": row[2], "status": row[3]})


# ── Health ─────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
