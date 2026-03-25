# Payment Processing Service

A Python service that processes customer payments via the Stripe API. Handles
charge creation and refunds as part of the checkout flow.

## Key flows

- `process_payment(order_id, amount_cents, currency, customer_id)` — Creates a
  Stripe charge. Called after fraud check passes. Logs charge ID and status.
- `refund_payment(charge_id, reason)` — Refunds a previous charge. Used by
  customer support and automated return processing.

## Business context

Payments are processed in cents (e.g. 4200 = $42.00). Currency is ISO 4217.
Customers are identified by Stripe customer IDs (`cus_...`). Declined charges
(card errors) are expected at a low rate and should be captured as error spans.

Order values range from $30 to $4,200. Enterprise customers have higher average
order values ($1,000+).

## Stack

- stripe — Official Stripe Python SDK
- No HTTP framework (called as a library from the main checkout service)

## No observability yet

This service has zero OpenTelemetry instrumentation. The Stripe SDK has no
built-in OTel support.

The agent should apply Tier C (monkey-patching): replace `stripe.Charge.create`
and `stripe.Refund.create` with instrumented wrappers that emit CLIENT spans.

Expected instrumentation:
- `stripe.charge.create` (CLIENT span) — with `payment.provider=stripe`,
  `payment.amount_usd`, `payment.currency`, `payment.customer_id`,
  `payment.charge_id` (on success), `payment.status`
- `stripe.refund.create` (CLIENT span) — with `payment.charge_id`,
  `refund.reason`, `refund.id` (on success)
- Error paths: `record_exception` + `set_status(ERROR)` on `CardError`
