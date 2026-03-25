# EDOT Autopilot — OpenTelemetry Auto-Instrumentation for Any Language (Including COBOL, Perl, and Legacy Runtimes)

[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-compatible-blue?logo=opentelemetry)](https://opentelemetry.io)
[![Elastic EDOT](https://img.shields.io/badge/Elastic-EDOT-005571?logo=elastic)](https://www.elastic.co/docs/reference/opentelemetry)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/languages-50%2B-brightgreen)](smoke-tests/README.md)

OpenTelemetry auto-instrumentation for any language — modern or legacy — powered by Elastic EDOT, with full support for runtimes that have no OTel SDK.

---

## What makes this different

Every other auto-instrumentation tool stops at the languages with an official OpenTelemetry SDK. This project does not.

| | Datadog OneAgent | Dynatrace | Upstream OTel | This project |
|---|---|---|---|---|
| Java, Python, .NET, Node | ✅ | ✅ | ✅ | ✅ |
| Legacy .NET Framework 4.x | ⚠️ | ⚠️ | ❌ | ✅ |
| Python 2.7 / old frameworks | ❌ | ❌ | ❌ | ✅ |
| COBOL / RPG / Fortran | ❌ | ❌ | ❌ | ✅ |
| Perl / Bash / PowerShell | ❌ | ❌ | ❌ | ✅ |
| Classic ASP / VBScript | ❌ | ❌ | ❌ | ✅ |
| Business-aware span enrichment | ❌ | ❌ | ❌ | ✅ |
| Reads codebase before instrumenting | ❌ | ❌ | ❌ | ✅ |

> If you're dealing with a language in that bottom half of the table, this project was built for you. [⭐ Star it](https://github.com/gmoskovicz/edot-autopilot) — so it shows up when the next person searches for the same problem.

---

## What this is

A framework for making **any application** fully observable — regardless of language, age, or
runtime — by reading the code first, then instrumenting what actually matters to the business.

> **The core insight:** Standard auto-instrumentation shows you that `POST /checkout` took 2.3s.
> EDOT Autopilot shows you that a **$4,200 enterprise order failed the fraud check** for a customer
> who signed up 2 days ago — and correlates it to a spike in `fraud.score` across the same cohort.
> Same data. Completely different usefulness.

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

## Works with

- **Elastic APM** — primary telemetry backend; traces, logs, and metrics in one place
- **Kibana** — service maps, APM dashboards, ES|QL analytics, SLO management
- **Elastic Cloud** — fully managed deployment, Serverless supported
- **OpenTelemetry Collector** — optional intermediate collector for DCGM/Prometheus pipelines
- **Prometheus** — metrics scraping compatible via OTLP bridge
- **Grafana** — works alongside Elastic for teams running a mixed observability stack
- **GitHub Actions** — CI-friendly; smoke tests run headlessly against any Elastic endpoint
- **Docker** — full suite runs in a single `docker compose up` with no local runtimes required

---

## Repository structure

```
edot-autopilot/
├── CLAUDE.md                         # Drop into any repo → "Observe this project."
├── README.md                         # This file
├── llms.txt                          # LLM-readable project summary
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

## Frequently Asked Questions

### How do I add OpenTelemetry to a language without an SDK?
Use the Tier D telemetry sidecar pattern. EDOT Autopilot generates a lightweight Python HTTP server that runs alongside your application. Any language that can make an HTTP POST call — COBOL, Perl, Bash, PowerShell, VBScript — can send traces, logs, and metrics to it. The sidecar translates these to OTLP and forwards them to Elastic. No SDK required.

### How do I instrument a COBOL application with OpenTelemetry?
Drop `CLAUDE.md` into your repo root and run `Observe this project. My Elastic endpoint: <url>. My API key: <key>` in Claude Code. EDOT Autopilot will read your COBOL source, identify the business-critical batch jobs and program calls, generate a Python sidecar server, and produce COBOL `CALL` snippets using `libcurl` (or the HTTP facility available in your COBOL environment) that POST span data to the sidecar. Your COBOL program then appears in the Elastic APM service map alongside your modern services.

### How do I add observability to a legacy .NET Framework application?
Legacy .NET Framework 4.x has partial upstream OTel SDK support. EDOT Autopilot handles it via Tier B (manual span wrapping around your key service methods) or Tier D (sidecar) for versions with no HTTP client. The smoke test in `11-tier-a-dotnet/` demonstrates the pattern with full traces, logs, and metrics flowing to Elastic.

### What is the difference between EDOT and the upstream OpenTelemetry collector?
EDOT (Elastic Distribution of OpenTelemetry) is Elastic's production-hardened distribution of the OTel SDK and collector, pre-configured for the Elastic stack. Unlike the upstream collector, EDOT ships with Elastic-specific processors (APM correlation, service map topology), default exporters pointed at Elastic Cloud, and agent management via Fleet. This project uses EDOT's OTLP HTTP endpoint directly — no collector process required.

### How do I send OpenTelemetry data directly to Elastic without a collector?
Use Elastic's OTLP ingest endpoint directly in your application. Create an API key in Elastic Cloud → Stack Management → API Keys, set the `Authorization: ApiKey <key>` header, and point your OTLP exporter at `https://<deployment>.apm.<region>.cloud.es.io`. The `o11y_bootstrap.py` helper in this repo handles this configuration for all three signal types (traces, logs, metrics) in one call.

### How do I add business context to OpenTelemetry spans?
Use `span.set_attribute("order.value_usd", 249.99)` for any data with business meaning. The key insight: standard auto-instrumentation captures `http.status_code=200`. Business-enriched instrumentation captures `customer.tier=enterprise`, `fraud.score=0.23`, `payment.method=amex`, `order.items_count=3`. These attributes make APM dashboards actionable — you can correlate latency spikes to customer segments, not just endpoints. See `CLAUDE.md` Phase 3 for the full enrichment guide.

---

## Built on

- [Elastic EDOT](https://www.elastic.co/docs/reference/opentelemetry) — Elastic Distributions of OpenTelemetry
- [OpenTelemetry](https://opentelemetry.io/) — vendor-neutral observability standard
- [OTel Hardware semconv](https://opentelemetry.io/docs/specs/semconv/hardware/gpu/) — `hw.gpu.*` GPU metrics
- [NVIDIA DCGM Exporter](https://github.com/NVIDIA/dcgm-exporter) — GPU cluster monitoring
- [elastic/agent-skills](https://github.com/elastic/agent-skills) — Elastic's Claude skill library

---

> **Repo topics to add** (improves discoverability on GitHub):
> `opentelemetry` `otel` `elastic` `edot` `observability` `tracing` `auto-instrumentation` `cobol` `legacy` `devops` `sre` `apm`
>
> Set these at: https://github.com/gmoskovicz/edot-autopilot → About → Topics
