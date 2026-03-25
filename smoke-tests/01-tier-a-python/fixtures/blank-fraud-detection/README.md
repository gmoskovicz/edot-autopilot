# Fraud Detection Service

A FastAPI REST API for order processing with integrated fraud scoring and
payment charging.

## Key flows

- `POST /orders` — Customer places an order. Runs fraud score computation,
  charges payment gateway. Orders with `fraud_score > 0.75` are blocked (402).
  Enterprise customers get lower fraud baseline; free-tier gets extra scrutiny.
- `GET /orders/<order_id>` — Fetch a single order by ID.
- `GET /orders` — List orders, optionally filtered by `customer_id`.
- `GET /health` — Health check.

## Business context

Orders carry a `customer_tier` (standard / pro / enterprise). The fraud engine
produces a score 0.0–1.0 based on order value and tier. Scores above 0.75 block
the order before payment is attempted. High-value orders (> $1000) receive
extra fraud scrutiny.

Payment processing is handled by an external gateway — declined payments return
a 402.

## Stack

- FastAPI — HTTP layer
- Pydantic — request/response validation
- uvicorn — ASGI server
- In-memory dict store (simulates Postgres in prod)

## No observability yet

This service has zero OpenTelemetry instrumentation. All three signals
(traces, metrics, logs) are missing. The agent should apply Tier A
auto-instrumentation (opentelemetry-instrumentation-fastapi) and add business
span attributes: `fraud.score`, `fraud.decision`, `order.total_usd`,
`customer.tier`, `payment.status`.
