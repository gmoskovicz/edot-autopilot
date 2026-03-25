# Payment Webhook Receiver

A Falcon REST API that receives and processes Stripe payment webhook events.
Routes each event type to the appropriate business logic and logs outcomes.

## Key flows

- `POST /webhooks/stripe` — Receive a Stripe event envelope. Handles:
  - `charge.succeeded` — logs charge confirmation at INFO
  - `payment_intent.payment_failed` — logs failure details at WARNING
  - `charge.dispute.created` — logs dispute at ERROR
  Always returns `{"received": true}` with HTTP 200.
- `GET /health` — Health check.

## Business context

- Events arrive as Stripe webhook JSON envelopes with `type`, `livemode`, and
  `data.object` fields.
- `amount` in Stripe events is in cents; the app converts to USD for logging.
- Disputes are the most critical event: they must trigger alerts and are logged
  at ERROR severity.

## Stack

- Falcon 3.x — WSGI REST framework

## No observability yet

This service has zero OpenTelemetry instrumentation. There is no official EDOT
instrumentor for Falcon, so the agent must add Tier B manual span wrapping
(`with tracer.start_as_current_span(...)`) inside each `on_post` responder.
Run `Observe this project.` to add it.
