# IoT Sensor Gateway

A Tornado web server that receives temperature and humidity readings from
factory-floor sensors, detects anomalies, and stores them in memory.

## Key flows

- `POST /api/v1/sensors/reading` — Accept a JSON sensor reading. Validates
  required fields, runs anomaly detection, and returns `{"anomaly": bool}`.
  Responds 202 on success, 400 on bad input.
- `GET /health` — Health check.

## Anomaly rules

A reading is flagged as anomalous when any of the following are true:
- `temperature_c > 35.0` (overheating)
- `temperature_c < -10.0` (freezing; common in cold-storage sensors)
- `humidity_pct > 90.0` (condensation risk)

## Business context

Sensors report from named locations on the factory floor (e.g. `floor-1-west`,
`cold-storage`). Anomalies are logged at WARNING level and must trigger alerts
in the observability platform.

## Stack

- Tornado 6.x — async HTTP server

## No observability yet

This service has zero OpenTelemetry instrumentation. There is no official EDOT
instrumentor for Tornado, so the agent must add Tier B manual span wrapping
(`with tracer.start_as_current_span(...)`) inside each `RequestHandler` method.
Run `Observe this project.` to add it.
