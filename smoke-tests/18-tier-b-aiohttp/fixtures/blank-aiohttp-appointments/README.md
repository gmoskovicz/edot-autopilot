# Healthcare Appointment Sync

An aiohttp async web service that synchronises patient appointments from legacy
scheduling systems (Cerner, Epic) to a cloud calendar, detecting and resolving
scheduling conflicts.

## Key flows

- `POST /api/sync/appointments` — Accept a patient sync request. Iterates over
  each appointment and upserts it to the cloud calendar. Returns
  `{"synced": N, "conflicts": M}` counts. Responds 200 on success, 400 on bad
  input.
- `GET /health` — Health check.

## Business context

- `source_system`: identifies the origin legacy system (`legacy-cerner`,
  `legacy-epic`). Used for audit logging.
- Conflicts (20% simulated probability) are resolved automatically and logged
  at WARNING.
- `synced + conflicts` must always equal the total number of appointments in
  the request.

## Stack

- aiohttp 3.x — async WSGI/ASGI HTTP server and client

## No observability yet

This service has zero OpenTelemetry instrumentation. There is no official EDOT
instrumentor for aiohttp, so the agent must add Tier B manual span wrapping
(`with tracer.start_as_current_span(...)`) inside each handler coroutine.
Run `Observe this project.` to add it.
