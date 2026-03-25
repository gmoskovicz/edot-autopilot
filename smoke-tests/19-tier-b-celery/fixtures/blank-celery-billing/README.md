# Monthly Invoice Generation — Celery Worker

A Celery background task worker that handles monthly billing operations:
generating PDF invoices, emailing them to customers, and sending payment
reminders for overdue accounts.

## Key tasks

- `billing.generate_invoice(customer_id, billing_period, amount)` — Generate a
  PDF invoice for a customer's billing period and dispatch it via email.
  Returns `{"invoice_id": "INV-...", "delivered": bool}`.
- `billing.send_payment_reminder(customer_id, invoice_id, days_overdue, amount)`
  — Send a payment reminder. Uses email if overdue < 14 days, phone otherwise.
  Returns `{"reminder_id": "REM-...", "channel": "email"|"phone"}`.

## Business context

- Tasks run on the `billing` queue.
- `task_always_eager = True` is set for local development (tasks run
  synchronously without a broker).
- PDF generation takes ~30 ms; email delivery has a 5% bounce rate (logged at
  WARNING).
- Customer tiers: `CUST-ENT-*` (enterprise), `CUST-PRO-*` (pro),
  `CUST-FREE-*` (free).

## Stack

- Celery 5.x — distributed task queue
- Memory transport (`memory://`) for local dev; Redis in production

## No observability yet

This worker has zero OpenTelemetry instrumentation. There is no official EDOT
Celery instrumentor, so the agent must add Tier B manual span wrapping
(`with tracer.start_as_current_span(...)`) inside each `@app.task` function.
Run `Observe this project.` to add it.
