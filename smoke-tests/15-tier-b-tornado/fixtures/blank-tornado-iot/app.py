"""
IoT Sensor Gateway — Tornado Web Server

No observability. Run `Observe this project.` to add it.

Receives temperature and humidity readings from factory-floor sensors,
validates the values, detects anomalies, and stores them in memory.
Anomalies are flagged when temperature > 35 °C, < -10 °C, or humidity > 90 %.
"""

import os
import json
import logging

import tornado.ioloop
import tornado.web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory reading store (replace with time-series DB in production)
readings_store: list[dict] = []


def is_anomaly(temperature_c: float, humidity_pct: float) -> bool:
    """Return True if the reading is outside safe operating ranges."""
    return temperature_c > 35.0 or temperature_c < -10.0 or humidity_pct > 90.0


class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_status(200)
        self.write({"status": "ok"})


class SensorReadingHandler(tornado.web.RequestHandler):
    """
    POST /api/v1/sensors/reading

    Body (JSON):
        sensor_id     (str)   — unique sensor identifier
        location      (str)   — physical location label
        temperature_c (float) — temperature in degrees Celsius
        humidity_pct  (float) — relative humidity percentage

    Responses:
        202  — reading accepted; anomaly flag returned
        400  — missing required fields
    """

    def post(self):
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, ValueError):
            self.set_status(400)
            self.write({"error": "invalid JSON"})
            return

        sensor_id    = body.get("sensor_id")
        location     = body.get("location")
        temperature  = body.get("temperature_c")
        humidity     = body.get("humidity_pct")

        if any(v is None for v in [sensor_id, location, temperature, humidity]):
            self.set_status(400)
            self.write({"error": "missing required fields"})
            return

        anomaly = is_anomaly(temperature, humidity)

        reading = {
            "sensor_id":     sensor_id,
            "location":      location,
            "temperature_c": temperature,
            "humidity_pct":  humidity,
            "anomaly":       anomaly,
        }
        readings_store.append(reading)

        if anomaly:
            logger.warning(
                "sensor anomaly detected",
                extra={"sensor_id": sensor_id, "location": location,
                       "temperature_c": temperature, "humidity_pct": humidity},
            )
        else:
            logger.info(
                "sensor reading ingested",
                extra={"sensor_id": sensor_id, "location": location,
                       "temperature_c": temperature, "humidity_pct": humidity},
            )

        self.set_status(202)
        self.write({"status": "accepted", "anomaly": anomaly})


def make_app():
    return tornado.web.Application([
        (r"/health", HealthHandler),
        (r"/api/v1/sensors/reading", SensorReadingHandler),
    ])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8888))
    app = make_app()
    app.listen(port)
    logger.info(f"IoT gateway listening on port {port}")
    tornado.ioloop.IOLoop.current().start()
