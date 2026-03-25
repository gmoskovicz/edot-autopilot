# EDOT Autopilot — Business-Aware Observability for Any Codebase

> **The core insight:** Standard auto-instrumentation shows you that `POST /checkout` took 2.3s.
> EDOT Autopilot shows you that a **$4,200 enterprise order failed the fraud check** for a customer
> who signed up 2 days ago — and correlates it to a spike in `fraud.score` across the same cohort.
> Same data. Completely different usefulness.

---

## What this is

A framework for making **any application** fully observable — regardless of language, age, or
runtime — by reading the code first, then instrumenting what actually matters to the business.

Every test in this repo emits all three OpenTelemetry signal types to Elastic:

| Signal | What you get |
|--------|-------------|
| **Traces** | Spans with business context — `order.value_usd`, `customer.tier`, `fraud.decision` |
| **Logs** | Structured records correlated to spans via `trace.id` — searchable in Kibana Logs |
| **Metrics** | Counters + histograms — `checkout.requests`, `hw.gpu.utilization`, `training.loss` |

---

## The four-tier coverage model

No other tool has a graceful degradation strategy that covers every runtime ever built.

| Tier | Strategy | When to use | Examples |
|------|----------|-------------|---------|
| **A** — Native OTel SDK | App imports OTel directly | New services, greenfield | Python, Node.js, Java, Go, Ruby, .NET, PHP |
| **B** — Manual span wrapping | Decorator/wrapper at startup | Frameworks without auto-instrumentation | Django ORM, Flask raw, Tornado, Bottle, Falcon |
| **C** — Library monkey-patch | Patch third-party SDK at import | All call sites covered in one place | Stripe, Twilio, boto3, Redis, OpenAI, CUDA |
| **D** — HTTP sidecar bridge | Curl/HTTP to a local OTel proxy | No SDK exists for the runtime | COBOL, SAP ABAP, IBM RPG, PowerShell, MATLAB |

> **Every existing tool stops at Tier B and says "unsupported."**
> This one generates working instrumentation for Tier D — anything that can make an HTTP call.

---

## Smoke test suite — 53 tests, 50+ technologies

All tests confirmed green against a live Elastic Cloud Serverless deployment.

### Tier A — Native OTel SDK (7)
Python · Node.js · Java · Go · Ruby · .NET C# · PHP

### Tier B — Manual span wrapping (8)
Flask · Django ORM · Tornado · Bottle · Falcon · aiohttp · Celery tasks

### Tier C — Library monkey-patching (15)
Stripe · Twilio · SendGrid · boto3 S3/SQS · Redis · PyMongo · psycopg2 · httpx ·
Celery worker · pika/RabbitMQ · elasticsearch-py · Slack SDK · OpenAI SDK ·
**NVIDIA GPU / CUDA (nvidia-ml-py)**

### Tier D — Sidecar bridge and legacy simulations (22)
Bash · Perl · COBOL · PowerShell · SAP ABAP · IBM RPG (AS/400) · Classic ASP ·
VBA/Excel · MATLAB · R · Lua · Tcl · AWK · Fortran HPC · Delphi · ColdFusion ·
Julia · Nim · Ada · Zapier · **NVIDIA DCGM Exporter (multi-GPU training)**

### Cross-tier end-to-end (1)
A single trace flowing Tier A → B → C → D with a shared `trace_id`, visible as
4 connected services in Kibana Service Map.

See [`smoke-tests/README.md`](smoke-tests/README.md) for the full test inventory,
ES|QL queries, and Docker instructions.

---

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/gmoskovicz/edot-autopilot.git
cd edot-autopilot
cp .env.example .env
# Fill in ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY

# 2. Run all 53 smoke tests (Python only — no other runtimes needed)
cd smoke-tests
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
bash run-all.sh
```

**Or with Docker — zero local dependencies:**

```bash
# Run all tests in a single container
docker compose --env-file .env run --rm runner

# Run the full suite including Node.js, Bash, Perl
docker compose --env-file .env up --abort-on-container-exit
```

---

## NVIDIA GPU / CUDA observability

Two dedicated tests instrument GPU workloads end-to-end:

**`51-tier-c-cuda-nvml`** — monkey-patches `nvidia-ml-py` to capture LLM inference telemetry:
- Traces: `cuda.kernel.prefill`, `cuda.kernel.decode`, `cuda.htod_transfer`
- Metrics: `hw.gpu.utilization`, `hw.gpu.memory.usage` (official OTel `hw.gpu.*` semconv)
  plus `gpu.temperature_c`, `gpu.power_usage_w`, `gpu.sm_clock_mhz`
- Logs: per-request events with `llm.tokens_per_second`, `gpu.uuid`, `gpu.power_w`

**`52-tier-d-dcgm-exporter`** — simulates the DCGM Exporter → OTel Collector → Elastic pipeline
for a 4× H100 distributed training job:
- Metrics: `dcgm.tensor_pipe_active`, `dcgm.nvlink_bandwidth_gbps`, `dcgm.xid_errors`,
  `training.loss`, `training.samples_per_sec`

To run against a real GPU, replace the mock in `51-tier-c-cuda-nvml/smoke.py` with
`import pynvml; pynvml.nvmlInit()` — the instrumentation layer is unchanged.

---

## The sidecar: what makes "any language" real

`otel-sidecar/otel-sidecar.py` is a universal telemetry bridge. Any process that can make
an HTTP POST can emit spans, logs, and metrics to Elastic APM — zero changes to the legacy binary.

```
[COBOL on AIX]   --curl--> [sidecar:9411] --OTLP--> [Elastic Cloud]
[SAP ABAP]       --http--> [sidecar:9411] --OTLP--> [Elastic Cloud]
[Bash script]    --curl--> [sidecar:9411] --OTLP--> [Elastic Cloud]
[PowerShell]     --http--> [sidecar:9411] --OTLP--> [Elastic Cloud]
```

Supported actions: `event`, `start_span`, `end_span`, `log`, `metric_counter`,
`metric_gauge`, `metric_histogram`. See [`otel-sidecar/README.md`](otel-sidecar/README.md).

---

## Business enrichment: the differentiator

Generic auto-instrumentation gives you:
```
span: POST /api/checkout  http.status_code=500  duration=340ms
```

Business-enriched spans give you:
```
span: checkout.complete
  order.value_usd        = 4200.00
  order.item_count       = 3
  customer.tier          = enterprise
  customer.age_days      = 2
  fraud.score            = 0.87
  fraud.decision         = blocked
  payment.method         = wire_transfer
```

The second version is actionable at 2am. The first is not.

---

## Verify in Kibana

After running `bash run-all.sh`:

```
Observability → APM → Services           filter: service.name: smoke-*
Observability → Logs                     filter: service.name: smoke-*
Observability → APM → Service Map        (cross-tier shows 4 connected nodes)
```

ES|QL quick checks:
```sql
-- All smoke test spans (last 30 min)
FROM traces-apm*
| WHERE service.name LIKE "smoke-*"
| KEEP @timestamp, service.name, transaction.name, labels.customer_tier
| SORT @timestamp DESC | LIMIT 50

-- GPU inference performance
FROM traces-apm*
| WHERE service.name == "smoke-tier-c-cuda-nvml"
| KEEP @timestamp, span.name, labels.llm_model,
       labels.llm_tokens_per_second, labels.gpu_temperature_c, labels.gpu_power_w
| SORT @timestamp DESC | LIMIT 20

-- Cross-tier trace (all 4 tiers, one trace_id)
FROM traces-apm*
| WHERE service.name IN ("activation-api","legacy-billing-engine",
                         "payment-gateway-stripe","notification-sms-bash")
| KEEP @timestamp, service.name, transaction.name, trace.id
| SORT @timestamp DESC | LIMIT 20
```

---

## Repository structure

```
edot-autopilot/
├── CLAUDE.md                         # Drop into any repo → "Observe this project."
├── README.md                         # This file
├── .env.example                      # Credentials template
│
├── otel-sidecar/                     # Universal Tier D bridge (traces + logs + metrics)
│   ├── otel-sidecar.py
│   ├── Dockerfile
│   └── README.md
│
├── smoke-tests/                      # 53 smoke tests — all 4 tiers, 50+ technologies
│   ├── run-all.sh                    # Run everything locally
│   ├── runner.sh                     # Used by Docker runner container
│   ├── Dockerfile                    # Python runner image
│   ├── docker-compose.yml            # Full suite with service profiles
│   ├── o11y_bootstrap.py             # Shared helper: tracer + logger + meter
│   │
│   ├── 01-tier-a-python/             # Tier A: Python
│   ├── 02-tier-a-nodejs/             # Tier A: Node.js
│   ├── 08–12-tier-a-*/               # Tier A: Java / Go / Ruby / .NET / PHP
│   ├── 03,13–19-tier-b-*/            # Tier B: Flask / Django / Tornado / Bottle …
│   ├── 04,20–32,51-tier-c-*/         # Tier C: Stripe / Twilio / boto3 / CUDA …
│   ├── 05,33–52-tier-d-*/            # Tier D: COBOL / SAP / MATLAB / DCGM …
│   ├── 07-cross-tier-full-o11y/      # A→B→C→D with shared trace_id
│   └── 06-verify/                    # OTLP ping + ES content verification
│
└── tests/                            # Full integration test apps (per-tier)
    ├── tier-a-python-fastapi/
    ├── tier-a-nodejs-express/
    ├── tier-a-java-springboot/
    ├── tier-b-dotnet-framework/
    ├── tier-b-python27/
    ├── tier-c-stripe-monkey-patch/
    ├── tier-d-bash/
    ├── tier-d-cobol/
    ├── tier-d-perl/
    ├── tier-d-powershell/
    ├── tier-d-sap-abap/
    └── tier-d-ibm-as400/
```

---

## Built on

- [Elastic EDOT](https://www.elastic.co/docs/reference/opentelemetry) — Elastic Distributions of OpenTelemetry
- [OpenTelemetry](https://opentelemetry.io/) — vendor-neutral observability standard
- [OTel Hardware semconv](https://opentelemetry.io/docs/specs/semconv/hardware/gpu/) — `hw.gpu.*` GPU metrics
- [NVIDIA DCGM Exporter](https://github.com/NVIDIA/dcgm-exporter) — GPU cluster monitoring
