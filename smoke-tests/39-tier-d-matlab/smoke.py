#!/usr/bin/env python3
"""
Smoke test: Tier D — MATLAB (sidecar simulation).

Simulates a MATLAB signal processing script submitting observability via the
HTTP sidecar bridge. Business scenario: predictive maintenance pipeline —
ingest vibration sensor data, run FFT analysis, detect bearing fault frequencies,
trigger maintenance alert if anomaly confidence exceeds threshold.

Run:
    cd smoke-tests && python3 39-tier-d-matlab/smoke.py
"""

import os, sys, time, random, math
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-d-matlab"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

sensors_analyzed  = meter.create_counter("matlab.sensors_analyzed")
anomalies_found   = meter.create_counter("matlab.anomalies_detected")
fft_duration      = meter.create_histogram("matlab.fft_duration_ms", unit="ms")
vibration_rms     = meter.create_histogram("matlab.vibration_rms_g")

SENSORS = [
    {"sensor_id": "VIB-PUMP-01",   "asset": "Centrifugal Pump A",  "location": "Plant-1/Cooling", "sample_hz": 25600, "samples": 65536},
    {"sensor_id": "VIB-MOTOR-03",  "asset": "Drive Motor #3",      "location": "Plant-2/Press",   "sample_hz": 51200, "samples": 131072},
    {"sensor_id": "VIB-BEARING-07","asset": "Conveyor Bearing #7", "location": "Plant-1/Line-B",  "sample_hz": 25600, "samples": 65536},
    {"sensor_id": "VIB-FAN-02",    "asset": "Exhaust Fan #2",      "location": "Plant-3/HVAC",    "sample_hz": 12800, "samples": 32768},
]

def analyze_sensor(sensor):
    t0 = time.time()
    rms_g     = random.uniform(0.5, 4.5)
    anomaly_confidence = random.uniform(0.05, 0.95)
    fault_freq = random.uniform(80, 320)
    is_anomaly = anomaly_confidence > 0.75

    with tracer.start_as_current_span("MATLAB.predictive_maintenance", kind=SpanKind.INTERNAL,
            attributes={"matlab.script": "run_vibration_analysis.m",
                        "matlab.function": "predictive_maintenance_pipeline",
                        "sensor.id": sensor["sensor_id"], "sensor.asset": sensor["asset"],
                        "sensor.location": sensor["location"],
                        "signal.sample_hz": sensor["sample_hz"],
                        "signal.samples":   sensor["samples"]}) as span:

        with tracer.start_as_current_span("MATLAB.load_sensor_data", kind=SpanKind.INTERNAL,
                attributes={"matlab.function": "load_sensor_data", "sensor.id": sensor["sensor_id"]}):
            time.sleep(random.uniform(0.01, 0.03))

        with tracer.start_as_current_span("MATLAB.fft", kind=SpanKind.INTERNAL,
                attributes={"matlab.function": "fft", "signal.fft_points": sensor["samples"],
                            "signal.freq_resolution_hz": round(sensor["sample_hz"] / sensor["samples"], 4)}) as s:
            t_fft = time.time()
            time.sleep(random.uniform(0.05, 0.15))
            fft_dur = (time.time() - t_fft) * 1000
            s.set_attribute("signal.dominant_freq_hz", round(fault_freq, 2))
            fft_duration.record(fft_dur, attributes={"sensor.id": sensor["sensor_id"]})

        with tracer.start_as_current_span("MATLAB.bearing_fault_detector", kind=SpanKind.INTERNAL,
                attributes={"matlab.function": "bearing_fault_detector",
                            "signal.rms_g": round(rms_g, 3)}):
            time.sleep(random.uniform(0.02, 0.05))
            if is_anomaly:
                anomalies_found.add(1, attributes={"sensor.asset": sensor["asset"]})

        dur = (time.time() - t0) * 1000
        span.set_attribute("signal.rms_g",              round(rms_g, 3))
        span.set_attribute("anomaly.confidence",         round(anomaly_confidence, 3))
        span.set_attribute("anomaly.fault_freq_hz",      round(fault_freq, 2))
        span.set_attribute("anomaly.detected",           is_anomaly)
        span.set_attribute("matlab.execution_ms",        round(dur, 2))

        if is_anomaly:
            span.set_status(StatusCode.ERROR, "bearing fault detected")

        sensors_analyzed.add(1, attributes={"sensor.location": sensor["location"].split("/")[0]})
        vibration_rms.record(rms_g, attributes={"sensor.asset": sensor["asset"]})

        level = "warning" if is_anomaly else "info"
        log_fn = logger.warning if is_anomaly else logger.info
        log_fn("vibration analysis complete",
               extra={"sensor.id": sensor["sensor_id"], "sensor.asset": sensor["asset"],
                      "signal.rms_g": round(rms_g, 3), "anomaly.confidence": round(anomaly_confidence, 3),
                      "anomaly.detected": is_anomaly, "anomaly.fault_freq_hz": round(fault_freq, 2)})

    return rms_g, anomaly_confidence, is_anomaly

print(f"\n[{SVC}] Simulating MATLAB predictive maintenance vibration analysis...")
for sensor in SENSORS:
    rms, conf, anom = analyze_sensor(sensor)
    icon = "🚨" if anom else "✅"
    print(f"  {icon} {sensor['sensor_id']:<20}  rms={rms:.2f}g  anomaly_conf={conf:.0%}  fault={anom}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
