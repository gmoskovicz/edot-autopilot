# User Authentication Service

A Flask REST API for user login with multi-factor authentication (MFA).
Validates credentials, dispatches a one-time password, and issues a session
token.

## Key flows

- `POST /auth/login` — Validate username/password hash, then dispatch a
  one-time password via the user's chosen MFA channel (SMS, email, or TOTP).
  Returns a session token on success (200) or rejects invalid credentials (401).
- `GET /health` — Health check.

## Business context

- Valid credentials: `password_hash` must start with `hash_` (simulated check).
- MFA channels: `sms`, `email`, `totp`. Each results in an OTP being sent to
  the user before the session is fully established.
- Sessions are short-lived tokens used to complete MFA verification.

## Stack

- Flask 3.x — HTTP layer

## No observability yet

This service has zero OpenTelemetry instrumentation. Traces (login flows, MFA
latency), metrics (login attempt counts, MFA duration), and structured logs are
all missing. Run `Observe this project.` to add Tier B manual span wrapping
(no official EDOT Flask instrumentor available for this legacy app version).
