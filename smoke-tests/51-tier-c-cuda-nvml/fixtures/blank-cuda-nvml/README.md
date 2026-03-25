# LLM Inference Service — blank fixture

A Python GPU inference service that calls NVML directly for GPU health monitoring, with no OTel instrumentation.

## What it does

- Initialises nvidia-ml-py (`pynvml.nvmlInit()`)
- Detects the first GPU and reads its name, UUID, driver version, and VRAM
- Runs a batch of LLM inference requests (llama-3-70b and mixtral-8x7b)
- Samples GPU utilization, memory usage, temperature, and power after each request

## SDK used

**nvidia-ml-py** (pynvml) — Python bindings for the NVIDIA Management Library (NVML).
Key calls:
- `nvmlDeviceGetMemoryInfo` — VRAM used/total
- `nvmlDeviceGetUtilizationRates` — GPU and memory bandwidth utilization (%)
- `nvmlDeviceGetTemperature` — core temperature (°C)
- `nvmlDeviceGetPowerUsage` — board power draw (mW)
- `nvmlDeviceGetClockInfo` — SM and memory clock frequencies (MHz)
- `nvmlDeviceGetPcieThroughput` — PCIe TX/RX bytes/sec

Since no real GPU is available, a mock `pynvml` class simulates a single
NVIDIA H100 SXM5 80GB with randomised but realistic metrics.

## No observability

This app has no OpenTelemetry instrumentation — it prints metrics to stdout only.
Run:

```
Observe this project.
```

The agent should assign **Tier C** and add:
- **Traces**: `cuda.inference_request` root span (SpanKind.SERVER) with child spans for HtoD transfer, prefill kernel, decode kernel, and DtoH transfer
- **Metrics**: `hw.gpu.utilization`, `hw.gpu.memory.usage`, `hw.gpu.memory.utilization` (OTel hw.gpu.* semconv) plus supplemental gauges for temperature, power, and SM clock
- **Logs**: structured events correlated to inference spans with `llm.model`, `llm.tokens_generated`, `gpu.utilization_pct`
