#!/usr/bin/env python3
"""
Smoke test: Tier D — Ada safety-critical systems (sidecar simulation).

Simulates an Ada program in an avionics context submitting observability via the
HTTP sidecar bridge. Business scenario: flight management system health monitor —
track sensor input validity, navigation accuracy, fuel calculations,
and autopilot mode transitions.

Run:
    cd smoke-tests && python3 49-tier-d-ada/smoke.py
"""

import os, sys, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-d-ada"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

sensor_cycles      = meter.create_counter("ada.sensor_cycles")
warnings_issued    = meter.create_counter("ada.system_warnings")
nav_accuracy       = meter.create_histogram("ada.nav_accuracy_m")
fuel_remaining     = meter.create_histogram("ada.fuel_remaining_kg")
cycle_duration     = meter.create_histogram("ada.cycle_duration_ms", unit="ms")

FLIGHT_PARAMS = {
    "flight_id":   "AA1234",
    "aircraft":    "B789",
    "phase":       "cruise",
    "altitude_ft": 37000,
    "speed_kts":   487,
    "fuel_total_kg": 42000,
}

MONITORING_CYCLES = [
    {"cycle": 1, "nav_err_m": 4.2,  "fuel_kg": 41_850, "iru_valid": True,  "gps_valid": True,  "mode": "VNAV"},
    {"cycle": 2, "nav_err_m": 5.1,  "fuel_kg": 41_620, "iru_valid": True,  "gps_valid": True,  "mode": "VNAV"},
    {"cycle": 3, "nav_err_m": 12.7, "fuel_kg": 41_390, "iru_valid": True,  "gps_valid": False, "mode": "VNAV"},  # GPS dropout
    {"cycle": 4, "nav_err_m": 8.3,  "fuel_kg": 41_165, "iru_valid": True,  "gps_valid": True,  "mode": "VNAV"},
    {"cycle": 5, "nav_err_m": 4.9,  "fuel_kg": 40_940, "iru_valid": True,  "gps_valid": True,  "mode": "VNAV"},
]

def run_monitoring_cycle(cycle_data):
    t0 = time.time()
    has_warning = not cycle_data["gps_valid"] or cycle_data["nav_err_m"] > 10.0

    with tracer.start_as_current_span("Ada.FMS.Navigation_Monitor", kind=SpanKind.INTERNAL,
            attributes={"ada.package": "FMS.Navigation_Monitor",
                        "ada.task":    "Navigation_Monitor_Task",
                        "flight.id":   FLIGHT_PARAMS["flight_id"],
                        "flight.phase": FLIGHT_PARAMS["phase"],
                        "ada.cycle":   cycle_data["cycle"]}) as span:

        with tracer.start_as_current_span("Ada.FMS.Read_IRU_Data", kind=SpanKind.INTERNAL,
                attributes={"ada.procedure": "Read_IRU_Data", "sensor.type": "IRU",
                            "sensor.valid": cycle_data["iru_valid"]}):
            time.sleep(0.002)

        with tracer.start_as_current_span("Ada.FMS.Read_GPS_Data", kind=SpanKind.INTERNAL,
                attributes={"ada.procedure": "Read_GPS_Data", "sensor.type": "GPS",
                            "sensor.valid": cycle_data["gps_valid"]}) as s:
            time.sleep(0.002)
            if not cycle_data["gps_valid"]:
                s.set_status(StatusCode.ERROR, "GPS_SENSOR_INVALID")
                warnings_issued.add(1, attributes={"ada.warning": "GPS_DROPOUT",
                                                    "flight.id": FLIGHT_PARAMS["flight_id"]})
                logger.warning("GPS sensor invalid — reverting to IRU-only navigation",
                               extra={"flight.id": FLIGHT_PARAMS["flight_id"],
                                      "sensor.type": "GPS", "ada.cycle": cycle_data["cycle"],
                                      "nav.accuracy_m": cycle_data["nav_err_m"]})

        with tracer.start_as_current_span("Ada.FMS.Compute_Nav_Accuracy", kind=SpanKind.INTERNAL,
                attributes={"ada.function": "Compute_RNP_Accuracy",
                            "nav.accuracy_m": cycle_data["nav_err_m"]}):
            time.sleep(0.001)
            if cycle_data["nav_err_m"] > 10.0:
                warnings_issued.add(1, attributes={"ada.warning": "RNP_EXCEEDED",
                                                    "flight.id": FLIGHT_PARAMS["flight_id"]})

        with tracer.start_as_current_span("Ada.FMS.Fuel_Computation", kind=SpanKind.INTERNAL,
                attributes={"ada.procedure": "Compute_Fuel_State",
                            "fuel.remaining_kg": cycle_data["fuel_kg"]}):
            time.sleep(0.001)
            eta_dest_min = 215 - cycle_data["cycle"] * 43
            fuel_reserve  = cycle_data["fuel_kg"] - 4200  # min reserve

        dur = (time.time() - t0) * 1000
        span.set_attribute("nav.accuracy_m",       cycle_data["nav_err_m"])
        span.set_attribute("nav.gps_valid",         cycle_data["gps_valid"])
        span.set_attribute("nav.iru_valid",          cycle_data["iru_valid"])
        span.set_attribute("fuel.remaining_kg",      cycle_data["fuel_kg"])
        span.set_attribute("fuel.reserve_kg",        fuel_reserve)
        span.set_attribute("flight.autopilot_mode",  cycle_data["mode"])
        span.set_attribute("ada.cycle_duration_ms",  round(dur, 3))

        if has_warning:
            span.set_status(StatusCode.ERROR, "navigation_warning")

        sensor_cycles.add(1, attributes={"flight.phase": FLIGHT_PARAMS["phase"],
                                          "flight.id": FLIGHT_PARAMS["flight_id"]})
        nav_accuracy.record(cycle_data["nav_err_m"], attributes={"flight.id": FLIGHT_PARAMS["flight_id"]})
        fuel_remaining.record(cycle_data["fuel_kg"], attributes={"flight.id": FLIGHT_PARAMS["flight_id"]})
        cycle_duration.record(dur, attributes={"ada.task": "Navigation_Monitor_Task"})

        logger.info("nav monitor cycle complete",
                    extra={"flight.id": FLIGHT_PARAMS["flight_id"], "ada.cycle": cycle_data["cycle"],
                           "nav.accuracy_m": cycle_data["nav_err_m"], "fuel.remaining_kg": cycle_data["fuel_kg"],
                           "nav.gps_valid": cycle_data["gps_valid"], "flight.autopilot_mode": cycle_data["mode"]})
    return has_warning

print(f"\n[{SVC}] Simulating Ada FMS navigation monitor ({FLIGHT_PARAMS['flight_id']}, "
      f"{FLIGHT_PARAMS['altitude_ft']}ft, {FLIGHT_PARAMS['speed_kts']}kts)...")
for cycle in MONITORING_CYCLES:
    warn = run_monitoring_cycle(cycle)
    icon = "⚠️ " if warn else "✅"
    gps  = "GPS:OK" if cycle["gps_valid"] else "GPS:FAIL"
    print(f"  {icon} Cycle {cycle['cycle']}  nav_err={cycle['nav_err_m']:>5.1f}m  {gps}  "
          f"fuel={cycle['fuel_kg']:,}kg  mode={cycle['mode']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
