# blank-dcgm-exporter — NVIDIA DCGM Exporter + OTel Collector (Python)

## What this program does

`dcgm_collector.py` is a Python 3.11 daemon that integrates NVIDIA DCGM
(Data Center GPU Manager) with an OTel Collector for GPU infrastructure
observability:

1. **DCGMCollector._init_dcgm** — initializes the pydcgm handle in embedded
   mode, creates a GPU group covering all GPUs, and sets up field watches for
   14 DCGM field IDs (utilization, memory, temperature, power, clock speeds,
   profiling counters, PCIe bandwidth, NVLink bandwidth, Xid errors)
2. **DCGMCollector.collect** — polls all watched field groups via
   `GetAllSinceLastCall` and returns a list of `GPUMetrics` dataclass snapshots
   per collection interval (default 1 second)
3. **PrometheusExporter.update** — updates Prometheus `Gauge`/`Counter` objects
   with the latest GPU snapshots, exposing them as Prometheus text format on
   `:9400/metrics` for the OTel Collector's Prometheus receiver to scrape
4. **run_collection_loop** — the main polling loop; logs a per-cycle summary
   including average GPU utilization, total cluster power draw, and any Xid
   error events

Real-world pipeline: DCGM Exporter → Prometheus scrape → OTel Collector
(prometheus receiver) → OTLP/HTTP → Elastic APM + Metrics.

GPU cluster: 4x NVIDIA H100 SXM5 80GB training a 70B LLM (DDP).

## Why it has no observability

This is a **Tier D** integration point. While `dcgm_collector.py` is itself
Python, the DCGM exporter ecosystem is designed to emit Prometheus metrics —
not OTel traces or spans. There are no span calls, no OTel SDK imports, no
HTTP POSTs to an OTLP endpoint, and no trace context propagation.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `dcgm_collector.py` to import and initialize the OTel Python SDK
   and emit collection cycle spans and GPU metric attributes via the sidecar
   API (or direct OTLP if the SDK can be installed)
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
