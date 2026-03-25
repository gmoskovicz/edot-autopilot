"""
Mobile E-Commerce API — Flask (backend for iOS/Android/RN apps)
No observability. Run `Observe this project.` to add OpenTelemetry.

This backend serves both iOS and Android mobile clients. It exposes:
  - Product catalog
  - Cart management
  - Checkout + payment
  - Order tracking with push notification triggers
"""
import os, uuid, random, time
from flask import Flask, jsonify, request

app = Flask(__name__)
products_db = [
  {"id":"p1","name":"Laptop Pro","price":1999.0,"in_stock":True,"category":"electronics"},
  {"id":"p2","name":"Headphones","price":299.99,"in_stock":True,"category":"audio"},
  {"id":"p3","name":"Keyboard",  "price":129.99,"in_stock":False,"category":"peripherals"},
]
orders = {}
carts  = {}

@app.route("/health")
def health(): return jsonify({"status":"ok"})

@app.route("/api/v1/products")
def get_products():
    category = request.args.get("category")
    result = [p for p in products_db if not category or p["category"] == category]
    return jsonify(result)

@app.route("/api/v1/cart", methods=["POST"])
def update_cart():
    body = request.get_json(force=True) or {}
    user_id = body.get("user_id","anon")
    items   = body.get("items",[])
    carts[user_id] = items
    total = sum(i.get("price",0)*i.get("qty",1) for i in items)
    return jsonify({"user_id":user_id,"items":items,"total_usd":total})

@app.route("/api/v1/checkout", methods=["POST"])
def checkout():
    body          = request.get_json(force=True) or {}
    user_id       = body.get("user_id","anon")
    customer_tier = body.get("customer_tier","free")
    items         = carts.get(user_id, body.get("items",[]))
    total = sum(i.get("price",0)*i.get("qty",1) for i in items)
    if total <= 0: return jsonify({"error":"cart is empty or total is zero"}), 400
    fraud_score = random.uniform(0,0.4)
    if customer_tier == "enterprise": fraud_score *= 0.5
    if fraud_score > 0.7: return jsonify({"error":"blocked","reason":"fraud"}), 402
    time.sleep(random.uniform(0.05,0.15))  # payment latency
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    orders[order_id] = {"order_id":order_id,"user_id":user_id,"total_usd":total,"status":"confirmed"}
    carts.pop(user_id, None)
    return jsonify(orders[order_id]), 201

@app.route("/api/v1/orders/<order_id>")
def get_order(order_id):
    order = orders.get(order_id)
    if not order: return jsonify({"error":"not found"}), 404
    return jsonify(order)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",6081)))
