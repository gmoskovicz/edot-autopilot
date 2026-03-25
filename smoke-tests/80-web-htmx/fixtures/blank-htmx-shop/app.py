"""
Shop — Flask + HTMX (HTML-first, Python backend)
No observability. Run `Observe this project.` to add OpenTelemetry.
"""
import os, uuid, random, time
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
orders = {}

PRODUCT_TEMPLATE = """
<!DOCTYPE html><html><head><title>ShopApp</title>
<script src="https://unpkg.com/htmx.org@1.9.10"></script></head>
<body>
<h1>ShopApp (HTMX)</h1>
<div hx-get="/products" hx-trigger="load">Loading...</div>
</body></html>
"""

PRODUCTS = [
  {"id":"p1","name":"Laptop Pro","price":1999.0,"in_stock":True},
  {"id":"p2","name":"Headphones","price":299.99,"in_stock":True},
  {"id":"p3","name":"Keyboard",  "price":129.99,"in_stock":False},
]

@app.route("/")
def index(): return render_template_string(PRODUCT_TEMPLATE)

@app.route("/health")
def health(): return jsonify({"status":"ok"})

@app.route("/products")
def products():
    rows = "".join(
        f'<div><span>{p["name"]} — ${p["price"]:.2f}</span>'
        f'<button hx-post="/cart/add" hx-vals=\'{{"product_id":"{p["id"]}"}}\' '
        f'{"" if p["in_stock"] else "disabled"}>{"Add" if p["in_stock"] else "OOS"}</button></div>'
        for p in PRODUCTS)
    return rows

@app.route("/cart/add", methods=["POST"])
def cart_add():
    product_id = request.form.get("product_id")
    p = next((x for x in PRODUCTS if x["id"] == product_id), None)
    if not p: return "Product not found", 404
    return f'<div>Added {p["name"]} to cart</div>'

@app.route("/orders", methods=["POST"])
def create_order():
    data = request.get_json(force=True) or {}
    total = sum(i.get("price_usd",0)*i.get("qty",1) for i in data.get("items",[]))
    if total <= 0: return jsonify({"error":"total must be > 0"}), 400
    order_id = str(uuid.uuid4())
    orders[order_id] = {"order_id":order_id,"total_usd":total,"status":"confirmed"}
    return jsonify(orders[order_id]), 201

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5080)))
