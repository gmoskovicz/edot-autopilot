#!/usr/bin/env python3
"""
Smoke test: Tier D — NVIDIA DCGM Exporter (sidecar simulation).

Simulates what the NVIDIA DCGM Exporter + OTel Collector pipeline would emit
when monitoring a multi-GPU training cluster. No GPU or DCGM installation
required — this is the Tier D sidecar pattern applied to GPU infrastructure.

Real-world pipeline this simulates:
  DCGM Exporter (:9400/metrics)
      ↓  Prometheus scrape
  OTel Collector (prometheus receiver)
      ↓  OTLP/HTTP
  Elastic (APM + Metrics)

Business scenario: Multi-GPU distributed training job (data-parallel DDP).
4x H100 GPUs training a 70B parameter language model. The DCGM exporter
emits per-GPU metrics every collection interval (1–5s). This test pushes
one collection cycle's worth of metrics directly via OTel Python SDK.

DCGM field IDs used (from default-counters.csv):
  DCGM_FI_DEV_GPU_UTIL, DCGM_FI_DEV_MEM_COPY_UTIL,
  DCGM_FI_DEV_FB_USED, DCGM_FI_DEV_FB_FREE,
  DCGM_FI_DEV_GPU_TEMP, DCGM_FI_DEV_POWER_USAGE,
  DCGM_FI_DEV_SM_CLOCK, DCGM_FI_DEV_MEM_CLOCK,
  DCGM_FI_PROF_PIPE_TENSOR_ACTIVE, DCGM_FI_PROF_DRAM_ACTIVE,
  DCGM_FI_PROF_PCIE_TX_BYTES, DCGM_FI_PROF_PCIE_RX_BYTES,
  DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL, DCGM_FI_DEV_XID_ERRORS

References:
  https://github.com/NVIDIA/dcgm-exporter
  https://opentelemetry.io/docs/specs/semconv/hardware/gpu/
  https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-api/dcgm-api-field-ids.html

Run:
    cd smoke-tests && python3 52-tier-d-dcgm-exporter/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-d-dcgm-exporter"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

# ── DCGM-style metrics (mirroring dcgm-exporter field names) ──────────────────
# Official hw.gpu.* conventions
dcgm_gpu_util          = meter.create_gauge("hw.gpu.utilization",
    description="DCGM_FI_DEV_GPU_UTIL — GPU utilisation fraction (0–1)")
dcgm_mem_util          = meter.create_gauge("hw.gpu.memory.utilization",
    description="DCGM_FI_DEV_MEM_COPY_UTIL — memory bandwidth utilisation (0–1)")
dcgm_fb_used           = meter.create_up_down_counter("hw.gpu.memory.usage",
    unit="By", description="DCGM_FI_DEV_FB_USED — framebuffer used (bytes)")
dcgm_fb_limit          = meter.create_up_down_counter("hw.gpu.memory.limit",
    unit="By", description="DCGM_FI_DEV_FB_FREE + FB_USED — total VRAM (bytes)")

# Supplemental DCGM fields (no official semconv yet)
dcgm_temp              = meter.create_gauge("dcgm.gpu_temp_celsius",
    unit="Cel", description="DCGM_FI_DEV_GPU_TEMP — GPU die temperature")
dcgm_power             = meter.create_gauge("dcgm.power_usage_watts",
    unit="W",   description="DCGM_FI_DEV_POWER_USAGE — board power draw")
dcgm_sm_clock          = meter.create_gauge("dcgm.sm_clock_mhz",
    unit="MHz", description="DCGM_FI_DEV_SM_CLOCK — streaming multiprocessor clock")
dcgm_mem_clock         = meter.create_gauge("dcgm.mem_clock_mhz",
    unit="MHz", description="DCGM_FI_DEV_MEM_CLOCK — memory clock")
dcgm_tensor_active     = meter.create_gauge("dcgm.tensor_pipe_active",
    description="DCGM_FI_PROF_PIPE_TENSOR_ACTIVE — tensor core utilisation (0–1)")
dcgm_dram_active       = meter.create_gauge("dcgm.dram_active",
    description="DCGM_FI_PROF_DRAM_ACTIVE — DRAM interface active fraction")
dcgm_pcie_tx           = meter.create_counter("dcgm.pcie_tx_bytes",
    unit="By",  description="DCGM_FI_PROF_PCIE_TX_BYTES — PCIe TX throughput")
dcgm_pcie_rx           = meter.create_counter("dcgm.pcie_rx_bytes",
    unit="By",  description="DCGM_FI_PROF_PCIE_RX_BYTES — PCIe RX throughput")
dcgm_nvlink_bw         = meter.create_gauge("dcgm.nvlink_bandwidth_gbps",
    unit="Gbit/s", description="DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL — NVLink aggregate BW")
dcgm_xid_errors        = meter.create_counter("dcgm.xid_errors",
    description="DCGM_FI_DEV_XID_ERRORS — NVIDIA Xid error events")

# Training-level metrics
ddp_iter_time          = meter.create_histogram("training.iteration_ms", unit="ms")
ddp_throughput         = meter.create_histogram("training.samples_per_sec")
ddp_loss               = meter.create_histogram("training.loss")

# ── Simulated GPU cluster ──────────────────────────────────────────────────────
GPUS = [
    {"index": 0, "uuid": f"GPU-{uuid.uuid4().hex[:8]}", "name": "NVIDIA H100 SXM5 80GB",
     "vram_gib": 80, "tdp_w": 700, "nvlink_gen": 4},
    {"index": 1, "uuid": f"GPU-{uuid.uuid4().hex[:8]}", "name": "NVIDIA H100 SXM5 80GB",
     "vram_gib": 80, "tdp_w": 700, "nvlink_gen": 4},
    {"index": 2, "uuid": f"GPU-{uuid.uuid4().hex[:8]}", "name": "NVIDIA H100 SXM5 80GB",
     "vram_gib": 80, "tdp_w": 700, "nvlink_gen": 4},
    {"index": 3, "uuid": f"GPU-{uuid.uuid4().hex[:8]}", "name": "NVIDIA H100 SXM5 80GB",
     "vram_gib": 80, "tdp_w": 700, "nvlink_gen": 4},
]

TRAINING_JOB = {
    "job_id":          f"train-{uuid.uuid4().hex[:8]}",
    "model":           "llama-3-70b-pretrain",
    "batch_size_global": 512,
    "seq_length":      4096,
    "total_steps":     100_000,
    "current_step":    42_817,
    "world_size":      len(GPUS),
}

COLLECTION_INTERVALS = 5  # simulate 5 DCGM scrape cycles

def collect_dcgm_cycle(cycle: int):
    """Simulate one DCGM Exporter scrape cycle across all GPUs."""
    cycle_t0 = time.time()
    gpu_snapshots = []

    with tracer.start_as_current_span("dcgm.collection_cycle", kind=SpanKind.INTERNAL,
            attributes={
                "dcgm.cycle":         cycle,
                "dcgm.gpu_count":     len(GPUS),
                "training.job_id":    TRAINING_JOB["job_id"],
                "training.model":     TRAINING_JOB["model"],
                "training.step":      TRAINING_JOB["current_step"] + cycle,
                "training.world_size":TRAINING_JOB["world_size"],
            }) as span:

        for gpu in GPUS:
            attrs = {
                "hw.type":   "gpu",
                "hw.id":     gpu["uuid"],
                "hw.name":   gpu["name"],
                "hw.vendor": "NVIDIA",
                "gpu.index": gpu["index"],
                "training.job_id": TRAINING_JOB["job_id"],
            }

            # Simulate realistic DDP training utilisation (high, sustained)
            util_pct       = random.uniform(92, 99)
            mem_pct        = random.uniform(85, 96)
            tensor_active  = random.uniform(0.78, 0.95)
            dram_active    = random.uniform(0.65, 0.88)
            temp_c         = random.randint(72, 84)
            power_w        = gpu["tdp_w"] * random.uniform(0.85, 0.98)
            sm_clock       = random.randint(1830, 1980)
            mem_clock      = random.randint(2600, 3200)
            fb_used_gib    = gpu["vram_gib"] * random.uniform(0.88, 0.96)
            pcie_tx        = random.randint(8_000_000, 18_000_000)
            pcie_rx        = random.randint(4_000_000, 12_000_000)
            nvlink_gbps    = random.uniform(380, 450)  # NVLink4 ~900 GB/s per direction
            xid_error      = 1 if random.random() < 0.02 else 0  # rare GPU errors

            fb_used_bytes  = int(fb_used_gib  * (1024**3))
            fb_total_bytes = int(gpu["vram_gib"] * (1024**3))

            # Record all DCGM-mapped OTel metrics
            dcgm_gpu_util.set(util_pct / 100.0, attributes={**attrs, "hw.gpu.task": "general"})
            dcgm_mem_util.set(mem_pct / 100.0,  attributes=attrs)
            dcgm_tensor_active.set(tensor_active, attributes=attrs)
            dcgm_dram_active.set(dram_active,   attributes=attrs)
            dcgm_temp.set(temp_c,               attributes=attrs)
            dcgm_power.set(power_w,             attributes=attrs)
            dcgm_sm_clock.set(sm_clock,         attributes=attrs)
            dcgm_mem_clock.set(mem_clock,       attributes=attrs)
            dcgm_nvlink_bw.set(nvlink_gbps,     attributes=attrs)
            dcgm_fb_used.add(0,                 attributes=attrs)  # gauge pattern
            dcgm_fb_limit.add(0,                attributes=attrs)
            dcgm_pcie_tx.add(pcie_tx,           attributes=attrs)
            dcgm_pcie_rx.add(pcie_rx,           attributes=attrs)
            if xid_error:
                dcgm_xid_errors.add(xid_error, attributes={**attrs, "dcgm.xid_code": 79})

            snap = {
                "util_pct": round(util_pct, 1), "temp_c": temp_c,
                "power_w": round(power_w, 0), "fb_used_gib": round(fb_used_gib, 1),
                "tensor_active": round(tensor_active, 2), "nvlink_gbps": round(nvlink_gbps, 0),
                "xid_error": xid_error,
            }
            gpu_snapshots.append(snap)

            if xid_error:
                logger.warning("DCGM Xid error detected",
                               extra={"gpu.index": gpu["index"], "gpu.uuid": gpu["uuid"],
                                      "dcgm.xid_code": 79, "dcgm.xid_description": "GPU has fallen off the bus",
                                      "training.job_id": TRAINING_JOB["job_id"]})
            else:
                logger.info("DCGM GPU metrics collected",
                            extra={"gpu.index": gpu["index"], "gpu.uuid": gpu["uuid"],
                                   "dcgm.gpu_util_pct": snap["util_pct"],
                                   "dcgm.temp_c": temp_c, "dcgm.power_w": snap["power_w"],
                                   "dcgm.tensor_active": snap["tensor_active"],
                                   "dcgm.nvlink_gbps": snap["nvlink_gbps"],
                                   "training.job_id": TRAINING_JOB["job_id"]})

        # Simulate training iteration metrics (emitted per step, not per GPU)
        iter_ms  = random.uniform(420, 550)
        samples_per_sec = TRAINING_JOB["batch_size_global"] / (iter_ms / 1000.0)
        loss     = 2.1 * (0.9998 ** (TRAINING_JOB["current_step"] + cycle)) + random.uniform(-0.02, 0.02)

        ddp_iter_time.record(iter_ms,       attributes={"training.model": TRAINING_JOB["model"]})
        ddp_throughput.record(samples_per_sec, attributes={"training.model": TRAINING_JOB["model"]})
        ddp_loss.record(loss,               attributes={"training.model": TRAINING_JOB["model"]})

        span.set_attribute("training.iter_ms",         round(iter_ms, 1))
        span.set_attribute("training.samples_per_sec", round(samples_per_sec, 1))
        span.set_attribute("training.loss",            round(loss, 4))
        span.set_attribute("dcgm.total_power_w",
                           round(sum(s["power_w"] for s in gpu_snapshots), 0))

        time.sleep(random.uniform(0.01, 0.03))  # realistic scrape overhead

    return gpu_snapshots, iter_ms, samples_per_sec, loss


print(f"\n[{SVC}] Simulating DCGM Exporter + OTel Collector for DDP training job...")
print(f"  Job:    {TRAINING_JOB['job_id']}  ({TRAINING_JOB['model']})")
print(f"  GPUs:   {len(GPUS)}x {GPUS[0]['name']}")
print(f"  Step:   {TRAINING_JOB['current_step']:,} / {TRAINING_JOB['total_steps']:,}")
print(f"  BS:     {TRAINING_JOB['batch_size_global']} global  |  seq_len={TRAINING_JOB['seq_length']}")
print()

for cycle in range(1, COLLECTION_INTERVALS + 1):
    snaps, iter_ms, sps, loss = collect_dcgm_cycle(cycle)
    avg_util = sum(s["util_pct"] for s in snaps) / len(snaps)
    avg_temp = sum(s["temp_c"]   for s in snaps) / len(snaps)
    total_pw = sum(s["power_w"]  for s in snaps)
    xid_any  = any(s["xid_error"] for s in snaps)
    icon     = "⚠️ " if xid_any else "✅"
    print(f"  {icon} Cycle {cycle}/{COLLECTION_INTERVALS}  "
          f"util={avg_util:.1f}%  temp={avg_temp:.0f}°C  "
          f"power={total_pw:.0f}W  "
          f"iter={iter_ms:.0f}ms  {sps:.0f}samp/s  loss={loss:.4f}"
          + ("  XID-ERROR!" if xid_any else ""))

o11y.flush()
print(f"\n[{SVC}] Done → Kibana APM → {SVC}")
print(f"\n  Kibana Metrics Explorer:")
print(f"    hw.gpu.utilization  (filter: hw.name: *H100*)")
print(f"    dcgm.power_usage_watts  |  dcgm.tensor_pipe_active")
print(f"    dcgm.nvlink_bandwidth_gbps  |  training.loss")
