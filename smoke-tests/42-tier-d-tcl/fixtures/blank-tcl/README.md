# blank-tcl — Network Device Configuration Management (Tcl/Expect)

## What this script does

`push_ospf_routes.tcl` is a Tcl 8.6 / Expect script that automates network
device configuration changes via SSH:

1. **spawn_ssh** — opens an SSH session to the target device using a key-based
   connection (Expect `spawn ssh`)
2. **send_commands** — enters privileged configuration mode and pushes each
   OSPF route change (add/modify/withdraw) using platform-specific CLI syntax
   (Cisco IOS/IOS-XR/NX-OS, Juniper JunOS)
3. **verify_bgp** — runs `show bgp summary` (or equivalent) to confirm that
   BGP peers are still up after the route change
4. **collect_interface_stats** — polls interface counters to detect any
   unexpected errors introduced by the route change
5. **commit/save** — commits the configuration (JunOS `commit`) or writes to
   NVRAM (IOS `write memory`) and disconnects

Target devices: 4 routers/switches across DC1 and DC2 (Cisco IOS, IOS-XR,
NX-OS, Juniper JunOS). Route changes: 3 OSPF prefixes.

## Why it has no observability

This is a **Tier D** legacy application. Tcl/Expect scripts have no
OpenTelemetry SDK. The Tcl runtime cannot load native OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`log_message` procedure calls writing to stderr.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `push_ospf_routes.tcl` to add `http::geturl` (Tcl `http` package)
   POST calls targeting the sidecar so that each network operation emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
