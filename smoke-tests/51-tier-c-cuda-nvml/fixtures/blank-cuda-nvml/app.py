"""
LLM Inference Service — GPU monitoring via nvidia-ml-py (pynvml)

No observability. Run `Observe this project.` to add it.
"""

import uuid
import time
import random


# ── Mock pynvml (simulates real nvidia-ml-py without a GPU) ───────────────────
# On a real GPU host, replace this block with:
#   import pynvml
#   pynvml.nvmlInit()

class _MockNVMLMemInfo:
    def __init__(self, total, used):
        self.total = total
        self.used = used
        self.free = total - used


class _MockNVMLUtilization:
    def __init__(self, gpu_pct, mem_pct):
        self.gpu = gpu_pct
        self.memory = mem_pct


class _MockNVMLDevice:
    """Simulates a single NVIDIA H100 SXM5 80GB GPU."""
    _uuid = f"GPU-{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:4]}"
    _name = "NVIDIA H100 SXM5 80GB"
    _total_mem = 80 * 1024 * 1024 * 1024  # 80 GiB

    def get_name(self):           return self._name
    def get_uuid(self):           return self._uuid
    def get_driver_version(self): return "545.23.08"

    def get_memory_info(self):
        used = int(self._total_mem * random.uniform(0.40, 0.85))
        return _MockNVMLMemInfo(self._total_mem, used)

    def get_utilization_rates(self):
        return _MockNVMLUtilization(random.randint(65, 98), random.randint(55, 90))

    def get_temperature(self):    return random.randint(62, 82)
    def get_power_usage(self):    return random.uniform(280, 700) * 1000  # mW

    def get_clock_info(self, clock_type):
        return {0: random.randint(1800, 1980), 1: random.randint(2619, 3200)}.get(clock_type, 1800)

    def get_pcie_throughput(self, direction):
        return random.randint(5_000_000, 15_000_000)  # bytes/sec


class pynvml:
    """Minimal nvidia-ml-py surface area used by this service."""
    NVML_CLOCK_SM = 0
    NVML_CLOCK_MEM = 1
    NVML_PCIE_UTIL_TX_BYTES = 0
    NVML_PCIE_UTIL_RX_BYTES = 1

    _inited = False
    _devices = [_MockNVMLDevice()]

    @classmethod
    def nvmlInit(cls):              cls._inited = True
    @classmethod
    def nvmlShutdown(cls):          cls._inited = False
    @classmethod
    def nvmlDeviceGetCount(cls):    return len(cls._devices)
    @classmethod
    def nvmlDeviceGetHandleByIndex(cls, idx): return cls._devices[idx]
    @classmethod
    def nvmlDeviceGetName(cls, h):  return h.get_name()
    @classmethod
    def nvmlDeviceGetUUID(cls, h):  return h.get_uuid()
    @classmethod
    def nvmlSystemGetDriverVersion(cls): return cls._devices[0].get_driver_version()
    @classmethod
    def nvmlDeviceGetMemoryInfo(cls, h): return h.get_memory_info()
    @classmethod
    def nvmlDeviceGetUtilizationRates(cls, h): return h.get_utilization_rates()
    @classmethod
    def nvmlDeviceGetTemperature(cls, h, sensor=0): return h.get_temperature()
    @classmethod
    def nvmlDeviceGetPowerUsage(cls, h): return h.get_power_usage()
    @classmethod
    def nvmlDeviceGetClockInfo(cls, h, t): return h.get_clock_info(t)
    @classmethod
    def nvmlDeviceGetPcieThroughput(cls, h, d): return h.get_pcie_throughput(d)


# ── Application code ───────────────────────────────────────────────────────────

INFERENCE_REQUESTS = [
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "llama-3-70b",
     "prompt_tokens": 512, "max_tokens": 256, "user": "api-prod-01"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "llama-3-70b",
     "prompt_tokens": 1024, "max_tokens": 512, "user": "api-prod-02"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "mixtral-8x7b",
     "prompt_tokens": 256, "max_tokens": 128, "user": "api-batch"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "llama-3-70b",
     "prompt_tokens": 2048, "max_tokens": 1024, "user": "api-prod-01"},
    {"req_id": f"INF-{uuid.uuid4().hex[:8]}", "model": "mixtral-8x7b",
     "prompt_tokens": 384, "max_tokens": 256, "user": "api-prod-03"},
]


def run_inference(req, handle):
    """Run one LLM inference request on the GPU and return token stats."""
    # Host → Device memory transfer
    time.sleep(random.uniform(0.002, 0.008))

    # Prefill (prompt processing on GPU)
    prefill_ms = req["prompt_tokens"] * random.uniform(0.06, 0.12)
    time.sleep(prefill_ms / 1000.0)

    # Autoregressive decode
    generated = min(req["max_tokens"], random.randint(64, req["max_tokens"]))
    decode_ms = generated * random.uniform(2.5, 5.0)
    time.sleep(decode_ms / 1000.0)

    # Device → Host transfer
    time.sleep(random.uniform(0.001, 0.004))

    # Sample GPU metrics (no OTel — just raw NVML calls)
    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    temp = pynvml.nvmlDeviceGetTemperature(handle)
    power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW → W

    print(
        f"  {req['req_id']} {req['model']}: gen={generated}tok "
        f"gpu={util.gpu}% mem={mem.used / (1024**3):.1f}GiB "
        f"temp={temp}C power={power:.0f}W"
    )
    return generated


if __name__ == "__main__":
    pynvml.nvmlInit()
    gpu_count = pynvml.nvmlDeviceGetCount()
    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    gpu_name = pynvml.nvmlDeviceGetName(handle)
    gpu_uuid = pynvml.nvmlDeviceGetUUID(handle)
    driver = pynvml.nvmlSystemGetDriverVersion()
    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)

    print(f"GPU: {gpu_name} | driver {driver} | {mem_info.total / (1024**3):.0f} GiB VRAM")

    for req in INFERENCE_REQUESTS:
        run_inference(req, handle)

    pynvml.nvmlShutdown()
    print("Done")
