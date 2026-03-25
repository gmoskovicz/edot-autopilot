# blank-ibm-rpg — Warehouse Inventory Cycle Count (WHINV001)

## What this program does

`WHINV001.rpgle` is an IBM RPG IV program running on IBM i (AS/400) in the
`WHPRDLIB` library. It performs the nightly warehouse cycle-count reconciliation:

1. **READ_INVMST** — reads the `INVMSTPF` inventory master VSAM file
   sequentially, one item at a time
2. **CYCLE_COUNT** — compares physical count against system quantity,
   computing a variance for each item
3. **WRITE_INVADJF** — if a variance is detected, writes an adjustment record
   to `INVADJPF` with the adjustment type `CC` (cycle count)
4. **TRIGGER_REPLENISHMENT** — if the counted quantity is at or below the
   item's reorder point, creates a replenishment order in `RPLORDF`
5. **WRITE_SUMMARY** — logs a batch summary (items counted, adjustments,
   replenishments) to the job log

The program is submitted to the `WHBATCH` job queue daily at 06:00, before
the warehouse opens.

## Why it has no observability

This is a **Tier D** legacy program. IBM RPG IV on IBM i has no supported
OpenTelemetry SDK. The AS/400 runtime cannot load native OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`DSPLY` statements writing to the IBM job log.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Add HTTP POST calls (using QShell `curl` or a CL wrapper) to WHINV001.rpgle
   so that CYCLE_COUNT, READ_INVMST, WRITE_INVADJF, and TRIGGER_REPLENISHMENT
   each emit spans via the sidecar API
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
