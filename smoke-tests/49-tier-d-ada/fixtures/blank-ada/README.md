# blank-ada — FMS Navigation Health Monitor (Ada)

## What this program does

`fms_navigation.adb` is an Ada 2022 package body (compiled with GNAT Pro 24.2)
implementing the Flight Management System navigation health monitor. The cyclic
task `Navigation_Monitor_Task` runs at 100ms on VxWorks 653:

1. **Read_IRU_Data** — reads IRU (Inertial Reference Unit) data from the ARINC
   429 bus: heading, pitch, roll, latitude, longitude, ground speed, and
   validity flag
2. **Read_GPS_Data** — reads GPS receiver data from the ARINC 429 bus:
   position, altitude, speed, track, HDOP, satellite count, and validity flag;
   sets span status to ERROR and logs a warning when GPS is invalid
3. **Compute_RNP_Accuracy** — computes the blended IRU/GPS Estimated Position
   Error (EPE) using a simplified UERE model; flags an RNP exceeded warning if
   EPE > 0.3 NM required threshold
4. **Compute_Fuel_State** — reads fuel quantity from ARINC 429 labels, computes
   total fuel remaining (kg), fuel flow (kg/hr), and ETA to destination
5. **Cycle summary** — logs each 100ms cycle result with navigation accuracy,
   GPS status, fuel remaining, and autopilot mode

Flight scenario: AA1234, Boeing 787, cruise at FL370, 487 kts.

## Why it has no observability

This is a **Tier D** legacy safety-critical application. Ada on DO-178C
avionics platforms has no OpenTelemetry SDK. The ARINC 653 RTOS partitioned
environment does not permit dynamic library loading or network sockets in the
navigation partition.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`Put_Line` statements to the serial debug console.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `fms_navigation.adb` to add GNAT.Sockets HTTP POST calls (or a C
   interop wrapper calling `libcurl`) targeting the sidecar so that each
   monitoring cycle emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
