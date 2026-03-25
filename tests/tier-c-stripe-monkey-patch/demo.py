"""
Demo: existing payment code with ZERO changes.
The instrumentation happens purely by importing stripe_instrumented before stripe.

In a real app this import would be at the top of your app's __init__.py or main.py.
"""

import stripe_instrumented  # noqa: F401 — patches stripe at import time

import stripe
import os

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_demo_key")

print("Simulating Stripe payment flow (spans sent to Elastic)...")

# This is EXISTING application code — not touched by the instrumentation
try:
    charge = stripe.Charge.create(
        amount=420000,          # $4,200.00 in cents
        currency="usd",
        customer="cus_enterprise_001",
        description="Enterprise license renewal",
    )
    print(f"Charge created: {charge['id']} status={charge['status']}")
except stripe.StripeError as e:
    print(f"Stripe error: {e}")

print("Done. Check Kibana → APM → Services → stripe-tier-c")
