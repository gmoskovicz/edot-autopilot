# Tier C — Stripe SDK Monkey-Patching

The Stripe Python SDK has no OpenTelemetry support. No EDOT plugin exists. But the Python language IS supported by EDOT.

**Strategy:** Wrap Stripe's public API methods at import time. Existing application code needs zero changes.

## The key insight

```python
# BEFORE — one line added to your app's startup:
import stripe_instrumented  # patches stripe.Charge.create, stripe.PaymentIntent.create

# AFTER — this existing code now emits spans automatically:
stripe.Charge.create(amount=420000, currency="usd", customer="cus_001")
# → span: stripe.charge.create
#     payment.amount = 420000
#     payment.currency = usd
#     payment.customer_id = cus_001
#     payment.charge_id = ch_xxx
#     payment.status = succeeded
```

## Run

```bash
pip install -r requirements.txt

export ELASTIC_OTLP_ENDPOINT=https://<your-deployment>.ingest.<region>.gcp.elastic.cloud:443
export ELASTIC_API_KEY=<your-base64-api-key>
export OTEL_SERVICE_NAME=stripe-tier-c
export STRIPE_SECRET_KEY=sk_test_your_key  # optional, demo mode works without it

python demo.py
```

## Extend to other unsupported SDKs

The same pattern works for: Twilio, SendGrid, Braintree, PayPal SDK, SOAP clients, legacy ORMs, any library whose public API is not auto-instrumented by EDOT.
