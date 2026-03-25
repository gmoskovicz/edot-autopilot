# Order Management Service

A Flask REST API for processing customer orders. Handles order placement,
payment processing, fraud checking, and inventory management.

## Key flows

- `POST /orders` — Customer places an order. Runs fraud check, charges payment,
  decrements inventory. High-value orders (> $500) get extra fraud scrutiny.
- `GET /orders/<order_id>` — Fetch order details.
- `POST /orders/<order_id>/fulfil` — Mark order as fulfilled, trigger shipping.
- `GET /health` — Health check.

## Business context

Orders have a `customer_tier` (standard / premium / enterprise). Enterprise
customers get priority fraud scoring. The `fraud_score` is computed from
customer history — anything above 0.7 blocks the order.

## Stack

- Flask 3.x — HTTP layer
- SQLAlchemy 2.x — Order storage (SQLite for dev, Postgres in prod)
- requests — Calls external payment gateway at https://pay.internal/charge

## No observability yet

This service has zero OpenTelemetry instrumentation. All three signals
(traces, metrics, logs) are missing.
