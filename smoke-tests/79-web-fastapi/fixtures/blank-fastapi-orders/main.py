"""
Order API — FastAPI (Python)
No observability. Run `Observe this project.` to add OpenTelemetry.
"""
import os, uuid, random
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Order API")
orders: dict = {}

class OrderItem(BaseModel):
    product_id: str; qty: int = 1; price_usd: float

class CreateOrderRequest(BaseModel):
    customer_id: str = "anon"; customer_tier: str = "standard"; items: list[OrderItem] = []

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/orders", status_code=201)
def create_order(req: CreateOrderRequest):
    total = sum(i.price_usd * i.qty for i in req.items)
    if total <= 0: raise HTTPException(400, "total must be > 0")
    fraud_score = random.uniform(0, 0.5)
    if req.customer_tier == "enterprise": fraud_score *= 0.5
    if fraud_score > 0.7: raise HTTPException(402, "order blocked: fraud_check_failed")
    order_id = str(uuid.uuid4())
    orders[order_id] = {"order_id": order_id, "customer_id": req.customer_id,
                        "total_usd": total, "status": "confirmed"}
    return orders[order_id]

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = orders.get(order_id)
    if not order: raise HTTPException(404, "not found")
    return order

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
