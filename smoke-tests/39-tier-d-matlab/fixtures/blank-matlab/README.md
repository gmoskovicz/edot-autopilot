# blank-matlab — Predictive Maintenance Vibration Analysis (MATLAB)

## What this script does

`script.m` is a MATLAB function (`run_vibration_analysis.m`) that implements a
predictive maintenance pipeline for rotating machinery:

1. **load_sensor_data** — loads raw accelerometer samples from NI-DAQ / OSIsoft
   PI historian (simulated with synthetic sinusoidal + noise signals)
2. **compute_fft** — computes the one-sided power spectrum using MATLAB's `fft`
   function with configurable FFT point count
3. **bearing_fault_detector** — identifies characteristic bearing fault
   frequencies (BPFO) by comparing spectral energy in the fault frequency band
   to total signal energy; also computes overall RMS vibration level
4. **trigger_maintenance_alert** — when anomaly confidence exceeds 0.75, writes
   a JSON alert file to the `alerts/` directory with sensor ID, asset, RMS,
   fault frequency, and recommended maintenance action

Sensors monitored: centrifugal pump, drive motors, conveyor bearings, HVAC fans
across manufacturing Plants 1–3.

## Why it has no observability

This is a **Tier D** legacy application. MATLAB scripts have no OpenTelemetry
SDK (MathWorks does not provide one). MATLAB cannot load native OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`fprintf` and JSON file writes to the `alerts/` directory.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `script.m` to add `webwrite` or `urlread2` HTTP POST calls targeting
   the sidecar so that each analysis step emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
