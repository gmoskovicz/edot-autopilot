#!/usr/bin/env python3
"""
Smoke test: Tier B — Tornado web framework (no EDOT instrumentation available).

Wraps Tornado RequestHandler methods manually.
Business scenario: IoT gateway receiving temperature/humidity sensor readings
from factory floor sensors, detecting anomalies.

Run:
    cd smoke-tests && python3 15-tier-b-tornado/smoke.py
"""

import os, sys, uuid, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-b-tornado"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

readings_ingested = meter.create_counter("iot.readings.ingested")
anomaly_counter   = meter.create_counter("iot.anomalies.detected")
temp_histogram    = meter.create_histogram("iot.temperature_celsius", unit="C")
humidity_hist     = meter.create_histogram("iot.humidity_pct", unit="%")


# ── Tier B: Tornado handler wrapper ───────────────────────────────────────────
def instrument_tornado_handler(handler_class, method="post"):
    """Wraps tornado.web.RequestHandler.post() / .get() with OTel span."""
    original = getattr(handler_class, method)
    def wrapped(self, *args, **kwargs):
        route = getattr(handler_class, "_route", "/unknown")
        with tracer.start_as_current_span(
            f"{method.upper()} {route}", kind=SpanKind.SERVER,
            attributes={"http.method": method.upper(), "http.route": route,
                        "framework": "tornado"},
        ) as span:
            return original(self, *args, **kwargs)
    setattr(handler_class, method, wrapped)
    return handler_class


# ── Mock Tornado RequestHandler ───────────────────────────────────────────────
class MockRequest:
    def __init__(self, body):
        self.body = body

class SensorReadingHandler:
    _route = "/api/v1/sensors/reading"

    def post(self, reading):
        """Existing handler code — NOT modified."""
        sensor_id   = reading["sensor_id"]
        location    = reading["location"]
        temp        = reading["temperature_c"]
        humidity    = reading["humidity_pct"]
        is_anomaly  = temp > 35.0 or temp < -10.0 or humidity > 90.0

        readings_ingested.add(1, attributes={"sensor.location": location})
        temp_histogram.record(temp,     attributes={"sensor.location": location})
        humidity_hist.record(humidity,  attributes={"sensor.location": location})

        if is_anomaly:
            anomaly_counter.add(1, attributes={"sensor.location": location})
            logger.warning("sensor anomaly detected",
                           extra={"sensor.id": sensor_id, "sensor.location": location,
                                  "reading.temperature_c": temp, "reading.humidity_pct": humidity})
        else:
            logger.info("sensor reading ingested",
                        extra={"sensor.id": sensor_id, "sensor.location": location,
                               "reading.temperature_c": temp, "reading.humidity_pct": humidity})

        return {"status": 202, "anomaly": is_anomaly}


instrument_tornado_handler(SensorReadingHandler, "post")

readings = [
    {"sensor_id": "SNS-F1-001", "location": "floor-1-west",    "temperature_c": 22.4, "humidity_pct": 48.1},
    {"sensor_id": "SNS-F1-002", "location": "floor-1-east",    "temperature_c": 38.7, "humidity_pct": 52.0},
    {"sensor_id": "SNS-F2-001", "location": "floor-2-server",  "temperature_c": 19.1, "humidity_pct": 42.5},
    {"sensor_id": "SNS-COLD-01","location": "cold-storage",    "temperature_c": -12.3,"humidity_pct": 65.0},
    {"sensor_id": "SNS-F2-002", "location": "floor-2-west",    "temperature_c": 21.0, "humidity_pct": 93.5},
]

handler = SensorReadingHandler()
print(f"\n[{SVC}] Simulating Tornado IoT gateway (manual wrapping)...")
for reading in readings:
    result = handler.post(reading)
    icon = "⚠️ " if result["anomaly"] else "✅"
    print(f"  {icon} {reading['sensor_id']}  {reading['location']:<20}  "
          f"T={reading['temperature_c']:>5.1f}°C  H={reading['humidity_pct']:>4.1f}%  "
          f"anomaly={result['anomaly']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
