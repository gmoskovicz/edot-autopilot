#!/usr/bin/env python3
"""
Smoke test: Tier C — NVIDIA GPU / CUDA via nvidia-ml-py (monkey-patched).

Patches the pynvml / nvidia-ml-py library so the test runs on any machine —
no GPU required. On a real GPU host, swap in the real nvidia-ml-py bindings
and remove the mock classes.

Business scenario: LLM inference serving — monitor GPU health and utilisation
while processing a batch of inference requests. Covers the full observability
story for ML inference platforms:

  Traces  → per-request inference spans with CUDA timing
  Logs    → structured events correlated to spans
  Metrics → GPU utilisation, memory, temperature, power, throughput

Semantic conventions used:
  hw.type          = "gpu"          (OTel Hardware semconv, Development status)
  hw.id            = GPU UUID
  hw.name          = GPU model
  hw.vendor        = "NVIDIA"
  hw.gpu.utilization         (OTel hw.gpu.* spec)
  hw.gpu.memory.usage        (OTel hw.gpu.* spec)
  hw.gpu.memory.limit        (OTel hw.gpu.* spec)
  hw.gpu.memory.utilization  (OTel hw.gpu.* spec)
  + supplemental: gpu.temperature_c, gpu.power_usage_w,
                  gpu.sm_clock_mhz, gpu.pcie_tx_bytes, gpu.pcie_rx_bytes

References:
  https://opentelemetry.io/docs/specs/semconv/hardware/gpu/
  https://github.com/NVIDIA/dcgm-exporter
  https://pypi.org/project/nvidia-ml-py/

Run:
    cd smoke-tests && python3 51-tier-c-cuda-nvml/smoke.py
"""

import os, sys, time, random, uuid, math
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-c-cuda-nvml"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

# ── OTel metrics — official hw.gpu.* semantic conventions ─────────────────────
gpu_utilization     = meter.create_gauge("hw.gpu.utilization",
                          description="Fraction of time the GPU was busy (0–1)")
gpu_mem_usage       = meter.create_up_down_counter("hw.gpu.memory.usage",
                          unit="By", description="GPU framebuffer memory in use")
gpu_mem_limit       = meter.create_up_down_counter("hw.gpu.memory.limit",
                          unit="By", description="Total GPU framebuffer memory")
gpu_mem_utilization = meter.create_gauge("hw.gpu.memory.utilization",
                          description="Fraction of GPU memory bandwidth in use (0–1)")

# Supplemental metrics (no official semconv yet — using DCGM-style names)
gpu_temperature     = meter.create_gauge("gpu.temperature_c",
                          unit="Cel", description="GPU core temperature (°C)")
gpu_power_usage     = meter.create_gauge("gpu.power_usage_w",
                          unit="W",   description="GPU board power draw (W)")
gpu_sm_clock        = meter.create_gauge("gpu.sm_clock_mhz",
                          unit="MHz", description="GPU SM clock frequency")
gpu_pcie_tx         = meter.create_counter("gpu.pcie_tx_bytes",
                          unit="By",  description="PCIe bytes transmitted by GPU")
gpu_pcie_rx         = meter.create_counter("gpu.pcie_rx_bytes",
                          unit="By",  description="PCIe bytes received by GPU")

# Inference-level metrics
inference_requests  = meter.create_counter("llm.inference_requests")
tokens_generated    = meter.create_counter("llm.tokens_generated")
inference_latency   = meter.create_histogram("llm.inference_latency_ms", unit="ms")
tokens_per_second   = meter.create_histogram("llm.tokens_per_second")


# ── Mock nvidia-ml-py (pynvml) ────────────────────────────────────────────────
# Replace this block with:
#   import pynvml
#   pynvml.nvmlInit()
# to use a real GPU.

class _MockNVMLMemInfo:
    def __init__(self, total, used):
        self.total = total
        self.used  = used
        self.free  = total - used

class _MockNVMLUtilization:
    def __init__(self, gpu_pct, mem_pct):
        self.gpu    = gpu_pct
        self.memory = mem_pct

class _MockNVMLDevice:
    """Simulates a single NVIDIA H100 SXM5 80GB GPU."""
    _uuid  = f"GPU-{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}"
    _name  = "NVIDIA H100 SXM5 80GB"
    _total_mem = 80 * 1024 * 1024 * 1024  # 80 GiB

    def get_name(self):         return self._name
    def get_uuid(self):         return self._uuid
    def get_driver_version(self): return "545.23.08"
    def get_memory_info(self):
        used = int(self._total_mem * random.uniform(0.40, 0.85))
        return _MockNVMLMemInfo(self._total_mem, used)
    def get_utilization_rates(self):
        return _MockNVMLUtilization(random.randint(65, 98), random.randint(55, 90))
    def get_temperature(self):  return random.randint(62, 82)
    def get_power_usage(self):  return random.uniform(280, 700) * 1000  # mW
    def get_clock_info(self, clock_type):
        return {0: random.randint(1800, 1980),  # SM clock
                1: random.randint(2619, 3200),  # mem clock
                }.get(clock_type, 1800)
    def get_pcie_throughput(self, direction):
        return random.randint(5_000_000, 15_000_000)  # bytes/sec


class pynvml:
    """Minimal nvidia-ml-py surface area used by this smoke test."""
    NVML_CLOCK_SM  = 0
    NVML_CLOCK_MEM = 1
    NVML_PCIE_UTIL_TX_BYTES = 0
    NVML_PCIE_UTIL_RX_BYTES = 1

    _inited  = False
    _devices = [_MockNVMLDevice()]

    @classmethod
    def nvmlInit(cls):           cls._inited = True
    @classmethod
    def nvmlShutdown(cls):       cls._inited = False
    @classmethod
    def nvmlDeviceGetCount(cls): return len(cls._devices)
    @classmethod
    def nvmlDeviceGetHandleByIndex(cls, idx): return cls._devices[idx]
    @classmethod
    def nvmlDeviceGetName(cls, h):            return h.get_name()
    @classmethod
    def nvmlDeviceGetUUID(cls, h):            return h.get_uuid()
    @classmethod
    def nvmlSystemGetDriverVersion(cls):      return cls._devices[0].get_driver_version()
    @classmethod
    def nvmlDeviceGetMemoryInfo(cls, h):      return h.get_memory_info()
    @classmethod
    def nvmlDeviceGetUtilizationRates(cls, h):return h.get_utilization_rates()
    @classmethod
    def nvmlDeviceGetTemperature(cls, h, sensor=0): return h.get_temperature()
    @classmethod
    def nvmlDeviceGetPowerUsage(cls, h):      return h.get_power_usage()
    @classmethod
    def nvmlDeviceGetClockInfo(cls, h, t):    return h.get_clock_info(t)
    @classmethod
    def nvmlDeviceGetPcieThroughput(cls, h, d): return h.get_pcie_throughput(d)


# ── Instrumented wrappers ──────────────────────────────────────────────────────

_orig_get_memory_info       = pynvml.nvmlDeviceGetMemoryInfo
_orig_get_utilization_rates = pynvml.nvmlDeviceGetUtilizationRates
_orig_get_temperature       = pynvml.nvmlDeviceGetTemperature
_orig_get_power_usage       = pynvml.nvmlDeviceGetPowerUsage
_orig_get_clock_info        = pynvml.nvmlDeviceGetClockInfo
_orig_get_pcie_throughput   = pynvml.nvmlDeviceGetPcieThroughput


def _collect_gpu_metrics(handle, gpu_idx: int, gpu_uuid: str, gpu_name: str):
    """Call all NVML getters, record OTel metrics, return snapshot dict."""
    attrs = {
        "hw.type":   "gpu",
        "hw.id":     gpu_uuid,
        "hw.name":   gpu_name,
        "hw.vendor": "NVIDIA",
        "gpu.index": gpu_idx,
    }

    mem   = _orig_get_memory_info(handle)
    util  = _orig_get_utilization_rates(handle)
    temp  = _orig_get_temperature(handle)
    power = _orig_get_power_usage(handle) / 1000.0   # mW → W
    sm_clk= _orig_get_clock_info(handle, pynvml.NVML_CLOCK_SM)
    tx    = _orig_get_pcie_throughput(handle, pynvml.NVML_PCIE_UTIL_TX_BYTES)
    rx    = _orig_get_pcie_throughput(handle, pynvml.NVML_PCIE_UTIL_RX_BYTES)

    # Official hw.gpu.* conventions
    gpu_utilization.set(util.gpu / 100.0,     attributes={**attrs, "hw.gpu.task": "general"})
    gpu_mem_usage.add(0,                       attributes=attrs)  # gauge-style: set via record
    gpu_mem_utilization.set(util.memory / 100.0, attributes=attrs)

    # Supplemental
    gpu_temperature.set(temp,   attributes=attrs)
    gpu_power_usage.set(power,  attributes=attrs)
    gpu_sm_clock.set(sm_clk,    attributes=attrs)
    gpu_pcie_tx.add(tx,         attributes=attrs)
    gpu_pcie_rx.add(rx,         attributes=attrs)

    return {
        "util_pct":     util.gpu,
        "mem_used_gib": mem.used / (1024**3),
        "mem_total_gib":mem.total / (1024**3),
        "mem_util_pct": util.memory,
        "temp_c":       temp,
        "power_w":      power,
        "sm_clock_mhz": sm_clk,
    }


# ── LLM inference requests ─────────────────────────────────────────────────────

INFERENCE_REQUESTS = [
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "llama-3-70b",    "prompt_tokens": 512,  "max_tokens": 256,  "user": "api-prod-01"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "llama-3-70b",    "prompt_tokens": 1024, "max_tokens": 512,  "user": "api-prod-02"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "mixtral-8x7b",   "prompt_tokens": 256,  "max_tokens": 128,  "user": "api-batch"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "llama-3-70b",    "prompt_tokens": 2048, "max_tokens": 1024, "user": "api-prod-01"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "mixtral-8x7b",   "prompt_tokens": 384,  "max_tokens": 256,  "user": "api-prod-03"},
]

def run_inference(req, handle, gpu_uuid, gpu_name):
    t0 = time.time()

    with tracer.start_as_current_span("cuda.inference_request", kind=SpanKind.SERVER,
            attributes={
                "llm.request_id":    req["req_id"],
                "llm.model":         req["model"],
                "llm.prompt_tokens": req["prompt_tokens"],
                "llm.max_tokens":    req["max_tokens"],
                "hw.type":           "gpu",
                "hw.id":             gpu_uuid,
                "hw.name":           gpu_name,
                "hw.vendor":         "NVIDIA",
            }) as span:

        # Host → Device memory transfer
        with tracer.start_as_current_span("cuda.htod_transfer", kind=SpanKind.INTERNAL,
                attributes={"cuda.direction": "host_to_device",
                            "cuda.bytes": req["prompt_tokens"] * 2,
                            "hw.id": gpu_uuid}):
            time.sleep(random.uniform(0.002, 0.008))

        # Prefill (processing the prompt on GPU)
        prefill_ms = req["prompt_tokens"] * random.uniform(0.06, 0.12)
        with tracer.start_as_current_span("cuda.kernel.prefill", kind=SpanKind.INTERNAL,
                attributes={"cuda.kernel":       "flash_attention_fwd",
                            "cuda.grid_dim":     "512x1x1",
                            "cuda.block_dim":    "128x1x1",
                            "llm.prompt_tokens": req["prompt_tokens"],
                            "hw.id": gpu_uuid}) as ks:
            time.sleep(prefill_ms / 1000.0)
            ks.set_attribute("cuda.duration_ms", round(prefill_ms, 2))

        # Autoregressive decode loop
        generated = min(req["max_tokens"], random.randint(64, req["max_tokens"]))
        decode_ms  = generated * random.uniform(2.5, 5.0)
        with tracer.start_as_current_span("cuda.kernel.decode", kind=SpanKind.INTERNAL,
                attributes={"cuda.kernel":          "rotary_embedding_fwd + matmul",
                            "llm.tokens_to_generate": generated,
                            "hw.id": gpu_uuid}) as ks:
            time.sleep(decode_ms / 1000.0)
            ks.set_attribute("cuda.duration_ms",  round(decode_ms, 2))
            ks.set_attribute("llm.tokens_generated", generated)

        # Device → Host transfer
        with tracer.start_as_current_span("cuda.dtoh_transfer", kind=SpanKind.INTERNAL,
                attributes={"cuda.direction": "device_to_host",
                            "cuda.bytes": generated * 2,
                            "hw.id": gpu_uuid}):
            time.sleep(random.uniform(0.001, 0.004))

        # Collect GPU metrics at end of request
        snapshot = _collect_gpu_metrics(handle, 0, gpu_uuid, gpu_name)

        total_ms  = (time.time() - t0) * 1000
        tps       = generated / (total_ms / 1000.0)

        span.set_attribute("llm.tokens_generated",   generated)
        span.set_attribute("llm.tokens_per_second",  round(tps, 1))
        span.set_attribute("llm.total_latency_ms",   round(total_ms, 2))
        span.set_attribute("gpu.utilization_pct",    snapshot["util_pct"])
        span.set_attribute("gpu.memory_used_gib",    round(snapshot["mem_used_gib"], 2))
        span.set_attribute("gpu.temperature_c",      snapshot["temp_c"])
        span.set_attribute("gpu.power_w",            round(snapshot["power_w"], 1))

        inference_requests.add(1, attributes={"llm.model": req["model"], "hw.id": gpu_uuid})
        tokens_generated.add(generated, attributes={"llm.model": req["model"]})
        inference_latency.record(total_ms, attributes={"llm.model": req["model"]})
        tokens_per_second.record(tps, attributes={"llm.model": req["model"]})

        logger.info("inference complete",
                    extra={
                        "llm.request_id":    req["req_id"],
                        "llm.model":         req["model"],
                        "llm.prompt_tokens": req["prompt_tokens"],
                        "llm.tokens_generated": generated,
                        "llm.tokens_per_second": round(tps, 1),
                        "llm.total_latency_ms":  round(total_ms, 2),
                        "gpu.uuid":              gpu_uuid,
                        "gpu.utilization_pct":   snapshot["util_pct"],
                        "gpu.memory_used_gib":   round(snapshot["mem_used_gib"], 2),
                        "gpu.temperature_c":     snapshot["temp_c"],
                        "gpu.power_w":           round(snapshot["power_w"], 1),
                    })

    return generated, total_ms, snapshot


# ── Main ──────────────────────────────────────────────────────────────────────

print(f"\n[{SVC}] Initialising nvidia-ml-py (pynvml)...")
pynvml.nvmlInit()

gpu_count = pynvml.nvmlDeviceGetCount()
driver    = pynvml.nvmlSystemGetDriverVersion()
print(f"  Driver: {driver}  |  GPUs detected: {gpu_count}")

handle    = pynvml.nvmlDeviceGetHandleByIndex(0)
gpu_name  = pynvml.nvmlDeviceGetName(handle)
gpu_uuid  = pynvml.nvmlDeviceGetUUID(handle)
mem_info  = pynvml.nvmlDeviceGetMemoryInfo(handle)
print(f"  GPU 0: {gpu_name}")
print(f"  UUID:  {gpu_uuid}")
print(f"  VRAM:  {mem_info.total / (1024**3):.0f} GiB total")

print(f"\n[{SVC}] Processing LLM inference requests...")
for req in INFERENCE_REQUESTS:
    gen, lat, snap = run_inference(req, handle, gpu_uuid, gpu_name)
    tps = gen / (lat / 1000.0)
    print(f"  ✅ {req['req_id']}  {req['model']:<18}  "
          f"prompt={req['prompt_tokens']:>4}tok  gen={gen:>4}tok  "
          f"{tps:>6.1f}tok/s  {lat:>6.0f}ms  "
          f"GPU={snap['util_pct']}%  {snap['temp_c']}°C  {snap['power_w']:.0f}W")

pynvml.nvmlShutdown()
o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
print(f"\n  ES|QL — GPU inference traces:")
print(f"    FROM traces-apm*")
print(f"    | WHERE service.name == \"{SVC}\"")
print(f"    | KEEP @timestamp, span.name, labels.llm_model,")
print(f"           labels.llm_tokens_per_second, labels.gpu_temperature_c, labels.gpu_power_w")
print(f"    | SORT @timestamp DESC | LIMIT 20")
