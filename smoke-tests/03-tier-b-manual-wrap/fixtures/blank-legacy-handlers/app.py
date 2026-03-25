"""
Legacy Billing Handlers — Plain Python Business Logic

No observability. Run `Observe this project.` to add it.

This module provides legacy handler functions for order processing and invoice
retrieval. They are called directly (not via HTTP framework) from internal
billing pipeline scripts.
"""

import uuid
import random
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_order(order_id: str, amount: float, tier: str) -> dict:
    """
    Process an incoming order through the fraud check.

    Args:
        order_id: Unique order identifier (e.g. ORD-A1B2C3)
        amount:   Order value in USD
        tier:     Customer tier — 'free', 'pro', or 'enterprise'

    Returns:
        dict with keys: status ('confirmed' | 'blocked'), status_code (201 | 402)
    """
    fraud_score = random.uniform(0, 1)
    # Enterprise customers get extra trust; high-value orders are riskier
    if tier == "enterprise":
        fraud_score *= 0.6
    if amount > 500:
        fraud_score = min(1.0, fraud_score + 0.1)

    decision = "blocked" if fraud_score > 0.85 else "approved"

    if fraud_score > 0.85:
        logger.warning(
            "order blocked by fraud engine",
            extra={"order_id": order_id, "fraud_score": round(fraud_score, 3),
                   "customer_tier": tier},
        )
        return {"status": "blocked", "status_code": 402}

    logger.info(
        "order confirmed",
        extra={"order_id": order_id, "order_value_usd": amount,
               "customer_tier": tier, "fraud_score": round(fraud_score, 3)},
    )
    return {"status": "confirmed", "status_code": 201}


def get_invoice(invoice_id: str, customer_id: str) -> dict:
    """
    Retrieve invoice details for a customer.

    Args:
        invoice_id:  Unique invoice identifier (e.g. INV-A1B2C3)
        customer_id: Customer account ID

    Returns:
        dict with keys: status ('found'), status_code (200), amount (float)
    """
    amount = random.uniform(100, 5000)

    logger.info(
        "invoice retrieved",
        extra={"invoice_id": invoice_id, "customer_id": customer_id,
               "invoice_amount": round(amount, 2)},
    )
    return {"status": "found", "status_code": 200, "amount": round(amount, 2)}


if __name__ == "__main__":
    # Quick smoke run — not the real entry point
    result = process_order("ORD-DEMO01", 299.99, "pro")
    print(f"process_order: {result}")
    result = get_invoice("INV-DEMO01", "CUST-PRO-007")
    print(f"get_invoice: {result}")
