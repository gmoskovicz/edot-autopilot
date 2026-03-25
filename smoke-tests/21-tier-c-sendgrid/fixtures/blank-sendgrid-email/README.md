# Email Notification Service

A Python service that sends transactional emails via SendGrid. Used for
password reset flows, welcome emails, and invoice notifications.

## Key flows

- `send_password_reset(user_email, reset_token)` — Sends a password reset
  email with a tokenized link. Template: `d-password-reset-v2`.
- `send_welcome_email(user_email, plan, first_name)` — Sends a welcome email
  on signup. Template: `d-welcome-v3`.
- `send_invoice_email(user_email, invoice_id, amount_usd)` — Sends a monthly
  invoice notification. Template: `d-invoice-v1`.

## Business context

All emails go through `sendgrid.SendGridAPIClient.send()`. The client is
instantiated per call (stateless). Responses include HTTP status code (202 =
accepted) and an `X-Message-Id` header for tracking.

Rate limiting (429) is possible under load. Failed sends should be retried
by the caller.

## Stack

- sendgrid — Official SendGrid Python SDK (no built-in OTel support)

## No observability yet

This service has zero OpenTelemetry instrumentation. The SendGrid SDK has no
built-in OTel support.

The agent should apply Tier C (monkey-patching): replace
`sendgrid.SendGridAPIClient.send` with an instrumented wrapper that emits
CLIENT spans.

Expected instrumentation:
- `sendgrid.send` (CLIENT span) with `email.to`, `email.subject`,
  `email.template_id`, `email.provider=sendgrid`
- On success: `email.status_code`, `email.message_id` attributes
- On error (rate limit, network failure): `record_exception` +
  `set_status(ERROR)`
- Metrics: counter `sendgrid.emails.sent` with `email.status` tag
