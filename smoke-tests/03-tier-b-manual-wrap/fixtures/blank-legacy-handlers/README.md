# Legacy Billing Handlers

Plain-Python handler functions for an internal billing pipeline. There is no
HTTP framework — handlers are called directly from batch scripts and internal
service glue code.

## Key entry points

- `process_order(order_id, amount, tier)` — Runs a fraud check on an incoming
  order. Returns `{"status": "confirmed"|"blocked", "status_code": 201|402}`.
  Orders with `fraud_score > 0.85` are blocked.
- `get_invoice(invoice_id, customer_id)` — Retrieves invoice details for a
  customer account. Returns `{"status": "found", "status_code": 200, "amount": float}`.

## Business context

- Customer tiers: `free`, `pro`, `enterprise`. Enterprise customers receive a
  trust discount on fraud scoring.
- Orders over $500 attract an additional fraud-risk surcharge.
- The fraud score is a float in `[0.0, 1.0]`. Anything above `0.85` blocks
  the order with a 402 response.

## Stack

- Pure Python (stdlib only) — `uuid`, `random`, `logging`
- No HTTP framework, no database

## No observability yet

These handlers have zero OpenTelemetry instrumentation. Traces, metrics, and
structured logs are all missing. Run `Observe this project.` to add Tier B
manual span wrapping.
