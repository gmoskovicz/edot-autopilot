# Server Decommission API

An internal infrastructure API built with the Bottle micro-framework. It
orchestrates the full decommission lifecycle for physical and virtual servers:
dependency checking, load-balancer draining, and archiving.

## Key flows

- `POST /api/infra/servers/<hostname>/decommission` — Decommission a server.
  Checks for active dependencies, drains the load balancer, then creates an
  archive record. Returns `{"archive_id": "ARCH-..."}` on success (200).
- `GET /health` — Health check.

## Business context

- `datacenter`: AWS region or on-prem datacenter identifier.
- `reason`: decommission reason (`end-of-life`, `replaced`, `hardware-failure`).
- Active dependencies (services that depend on this server) block or delay the
  drain step and are logged at WARNING.
- `connections_drained` is the number of LB connections cleared before shutdown.

## Stack

- Bottle 0.12.x — lightweight WSGI micro-framework

## No observability yet

This service has zero OpenTelemetry instrumentation. There is no official EDOT
instrumentor for Bottle, so the agent must add Tier B manual span wrapping
(`with tracer.start_as_current_span(...)`) inside each route function.
Run `Observe this project.` to add it.
