"""
Payment Processing Service — Stripe Charge API

No observability. Run `Observe this project.` to add it.
"""

import os
import uuid
import logging

import stripe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

stripe.api_key = os.environ.get("STRIPE_API_KEY", "sk_test_placeholder")

# ── Business logic ─────────────────────────────────────────────────────────────

def process_payment(order_id: str, amount_cents: int, currency: str, customer_id: str) -> dict:
    """
    Charge a customer via Stripe. Called from the checkout flow after
    fraud check passes.

    amount_cents: e.g. 4200 = $42.00
    currency: ISO 4217 code, e.g. "usd", "eur"
    customer_id: Stripe customer ID, e.g. "cus_abc123"
    """
    logger.info(f"Charging customer {customer_id} for order {order_id}: "
                f"{amount_cents} {currency.upper()}")

    charge = stripe.Charge.create(
        amount=amount_cents,
        currency=currency,
        customer=customer_id,
        description=f"Order {order_id}",
        metadata={"order_id": order_id},
    )

    logger.info(f"Charge {charge['id']} succeeded for order {order_id}")
    return {
        "order_id": order_id,
        "charge_id": charge["id"],
        "status": charge["status"],
        "amount_usd": amount_cents / 100,
    }


def refund_payment(charge_id: str, reason: str = "requested_by_customer") -> dict:
    """Refund a previously successful charge."""
    logger.info(f"Refunding charge {charge_id}: {reason}")

    refund = stripe.Refund.create(
        charge=charge_id,
        reason=reason,
    )

    logger.info(f"Refund {refund['id']} created for charge {charge_id}")
    return {
        "refund_id": refund["id"],
        "charge_id": charge_id,
        "status": refund["status"],
    }


# ── Sample payment run (used in local dev / smoke test) ───────────────────────
SAMPLE_PAYMENTS = [
    ("ORD-001", 420000,  "usd", "cus_enterprise_001"),  # $4200 enterprise
    ("ORD-002", 2999,    "usd", "cus_free_042"),         # $29.99 free tier
    ("ORD-003", 125000,  "eur", "cus_pro_007"),          # €1250 pro
    ("ORD-004", 89900,   "usd", "cus_pro_015"),          # $899 pro
    ("ORD-005", 349900,  "usd", "cus_enterprise_002"),   # $3499 enterprise
]

if __name__ == "__main__":
    for order_id, amount, currency, customer_id in SAMPLE_PAYMENTS:
        try:
            result = process_payment(order_id, amount, currency, customer_id)
            print(f"  {order_id}: {result['status']} charge={result['charge_id']}")
        except stripe.error.CardError as e:
            print(f"  {order_id}: DECLINED — {e}")
        except Exception as e:
            print(f"  {order_id}: ERROR — {e}")
