# EDOT Autopilot — Smoke Test Suite

> **53 smoke tests** across 4 tiers and 50+ technologies. Every test emits
> **traces + logs + metrics** to Elastic via OTLP/HTTP. All confirmed green
> against a live Elastic Cloud Serverless deployment.

---

## What this proves

Any application — regardless of language, framework, or runtime age — can be
made fully observable without modifying business logic. The four tiers model
the full spectrum of real-world scenarios:

| Tier | Approach | When to use |
|------|----------|-------------|
| **A** — Native OTel SDK | App imports OTel directly | New services, greenfield code |
| **B** — Manual span wrapping | Decorator/wrapper added at startup | Frameworks without auto-instrumentation |
| **C** — Library monkey-patching | Patch third-party SDK at import time | All call sites instrumented in one place |
| **D** — HTTP Sidecar bridge | Curl/HTTP to a local OTel proxy | Legacy runtimes with no SDK (COBOL, ABAP, etc.) |

---

## Quick start

```bash
# 1. Set your Elastic Cloud credentials
cp ../.env.example ../.env
# Fill in ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY

# 2. Install Python dependencies (one-time)
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

# 3. Run all 53 tests
cd smoke-tests
bash run-all.sh
```

**Expected output:** `✅ All 53 tests passed`

---

## Run with Docker (zero local dependencies)

```bash
# Run all Python tests — one container, all 48 Python smoke tests
docker compose --env-file ../.env run --rm runner

# Run the full suite including Node.js, Bash, Perl
docker compose --env-file ../.env up --abort-on-container-exit

# Run a specific tier only
docker compose --env-file ../.env run --rm runner bash runner.sh tier-c

# Run only the CUDA / GPU tests
docker compose --env-file ../.env run --rm runner bash runner.sh cuda

# Verify spans reached Elastic (OTLP ping for all 53 services)
docker compose --env-file ../.env run --rm verify
```

---

## Test inventory

### Tier A — Native OTel SDK (7 tests)

| # | Directory | Language | Business scenario |
|---|-----------|----------|-------------------|
| 01 | `01-tier-a-python` | Python | E-commerce checkout with fraud scoring |
| 02 | `02-tier-a-nodejs` | Node.js | Same checkout scenario, Node.js OTel SDK |
| 08 | `08-tier-a-java` | Java | Order processing — validate, charge, confirm |
| 09 | `09-tier-a-go` | Go | API gateway — auth JWT, route to upstream |
| 10 | `10-tier-a-ruby` | Ruby | SaaS subscription creation + first payment |
| 11 | `11-tier-a-dotnet` | .NET C# | Inventory stock transfers between warehouses |
| 12 | `12-tier-a-php` | PHP | CMS content API — auth, DB fetch, cache |

> Java, Go, Ruby, .NET, PHP each include both the native-language source file
> (`smoke.java`, `smoke.go`, etc.) and a `smoke.py` Python simulation that
> emits identical telemetry with the correct `service.name` — so Kibana always
> shows all 7 services even without those runtimes installed.

### Tier B — Manual span wrapping (8 tests)

| # | Directory | Framework | Business scenario |
|---|-----------|-----------|-------------------|
| 03 | `03-tier-b-manual-wrap` | Flask | Checkout handler wrapped at startup |
| 13 | `13-tier-b-django-orm` | Django ORM | Inventory reorder management command |
| 14 | `14-tier-b-flask-raw` | Flask raw | User authentication with MFA |
| 15 | `15-tier-b-tornado` | Tornado | IoT sensor gateway |
| 16 | `16-tier-b-bottle` | Bottle | Server decommission approval API |
| 17 | `17-tier-b-falcon` | Falcon | Payment webhook receiver |
| 18 | `18-tier-b-aiohttp` | aiohttp | Healthcare appointment sync |
| 19 | `19-tier-b-celery` | Celery | Invoice batch generation |

### Tier C — Library monkey-patching (15 tests)

| # | Directory | Library | Business scenario |
|---|-----------|---------|-------------------|
| 04 | `04-tier-c-monkey-patch` | Stripe | Payment processing |
| 20 | `20-tier-c-twilio` | Twilio | Appointment SMS reminders |
| 21 | `21-tier-c-sendgrid` | SendGrid | Password reset + welcome emails |
| 22 | `22-tier-c-boto3-s3` | boto3 S3 | Legal contract archival |
| 23 | `23-tier-c-boto3-sqs` | boto3 SQS | Order fulfillment queue |
| 24 | `24-tier-c-redis` | redis-py | Session cache |
| 25 | `25-tier-c-pymongo` | PyMongo | Product catalog |
| 26 | `26-tier-c-psycopg2` | psycopg2 | Daily analytics rollup |
| 27 | `27-tier-c-httpx` | httpx | FX rate fetcher |
| 28 | `28-tier-c-celery-worker` | Celery | Video transcoding job queue |
| 29 | `29-tier-c-rabbitmq` | pika (RabbitMQ) | Domain event bus |
| 30 | `30-tier-c-elasticsearch` | elasticsearch-py | Product search index |
| 31 | `31-tier-c-slack` | slack-sdk | Incident alerting |
| 32 | `32-tier-c-openai` | OpenAI SDK | Support ticket classification |
| 51 | `51-tier-c-cuda-nvml` | nvidia-ml-py | **LLM inference GPU monitoring** |

### Tier D — Sidecar bridge / legacy runtime simulations (22 tests)

| # | Directory | Runtime | Business scenario |
|---|-----------|---------|-------------------|
| 05 | `05-tier-d-sidecar` (bash) | Bash | ETL + backup jobs via curl |
| 05 | `05-tier-d-sidecar` (perl) | Perl | Invoice processing via LWP |
| 05 | `05-tier-d-sidecar` (python client) | Python | All three sidecar patterns |
| 33 | `33-tier-d-cobol-batch` | COBOL | Monthly payroll processing (PAYRLL01) |
| 34 | `34-tier-d-powershell` | PowerShell | Active Directory new-hire provisioning |
| 35 | `35-tier-d-sap-abap` | SAP ABAP | Purchase order creation (BAPI_PO_CREATE1) |
| 36 | `36-tier-d-ibm-rpg` | IBM RPG (AS/400) | Warehouse cycle count reconciliation |
| 37 | `37-tier-d-classic-asp` | Classic ASP | Insurance quote form |
| 38 | `38-tier-d-vba-excel` | VBA / Excel | Group P&L consolidation macro |
| 39 | `39-tier-d-matlab` | MATLAB | Predictive maintenance vibration analysis |
| 40 | `40-tier-d-r-statistical` | R | Credit risk logistic regression scoring |
| 41 | `41-tier-d-lua` | Lua | Game server session + economy events |
| 42 | `42-tier-d-tcl` | Tcl / Expect | Network device configuration push |
| 43 | `43-tier-d-awk-etl` | AWK | Access log ETL pipeline |
| 44 | `44-tier-d-fortran` | Fortran | WRF climate HPC model run |
| 45 | `45-tier-d-delphi` | Delphi / Object Pascal | Point-of-sale transactions |
| 46 | `46-tier-d-coldfusion` | ColdFusion / CFML | CMS content publishing pipeline |
| 47 | `47-tier-d-julia` | Julia | LSTM demand forecasting training |
| 48 | `48-tier-d-nim` | Nim | FIX 4.4 protocol message parser |
| 49 | `49-tier-d-ada` | Ada | Avionics FMS navigation monitor |
| 50 | `50-tier-d-zapier` | Zapier (no-code) | Lead nurturing workflow automation |
| 52 | `52-tier-d-dcgm-exporter` | NVIDIA DCGM | **Multi-GPU DDP training cluster** |

### Cross-tier end-to-end (1 test)

| # | Directory | Description |
|---|-----------|-------------|
| 07 | `07-cross-tier-full-o11y` | Service activation flowing Tier A → B → C → D with a **single shared `trace_id`**. Shows 4 connected services in Kibana Service Map. |

---

## NVIDIA GPU / CUDA observability

Two dedicated tests cover GPU/CUDA telemetry:

### `51-tier-c-cuda-nvml` — LLM inference monitoring
Monkey-patches `nvidia-ml-py` (`pynvml`) to emit GPU health metrics during
LLM inference (llama-3-70b, mixtral-8x7b). Uses the official
[OTel Hardware semantic conventions](https://opentelemetry.io/docs/specs/semconv/hardware/gpu/)
(`hw.gpu.*`) plus CUDA-specific span attributes.

**Signals emitted:**
- **Traces**: per-request spans → `cuda.htod_transfer`, `cuda.kernel.prefill`,
  `cuda.kernel.decode`, `cuda.dtoh_transfer`
- **Metrics** (`hw.gpu.*`): `hw.gpu.utilization`, `hw.gpu.memory.usage`,
  `hw.gpu.memory.utilization` + supplemental `gpu.temperature_c`,
  `gpu.power_usage_w`, `gpu.sm_clock_mhz`, `gpu.pcie_tx/rx_bytes`
- **Logs**: structured per-inference events with `llm.tokens_per_second`,
  `gpu.uuid`, `gpu.utilization_pct`, `gpu.power_w`

### `52-tier-d-dcgm-exporter` — Multi-GPU DDP training cluster
Simulates the [NVIDIA DCGM Exporter](https://github.com/NVIDIA/dcgm-exporter)
→ OTel Collector → Elastic pipeline for a 4× H100 distributed training job.

**Signals emitted:**
- **Traces**: `dcgm.collection_cycle` spans per scrape interval
- **Metrics**: Full DCGM field set — `dcgm.tensor_pipe_active`,
  `dcgm.dram_active`, `dcgm.nvlink_bandwidth_gbps`, `dcgm.xid_errors`,
  `training.loss`, `training.samples_per_sec`
- **Logs**: per-GPU collection events, Xid error alerts

**Running against a real GPU host:**
```python
# In 51-tier-c-cuda-nvml/smoke.py, replace the mock block with:
import pynvml
pynvml.nvmlInit()
# ... rest of the instrumentation is unchanged
```

**Kibana queries after running:**
```sql
-- GPU inference performance
FROM traces-apm*
| WHERE service.name == "smoke-tier-c-cuda-nvml"
| KEEP @timestamp, span.name, labels.llm_model,
       labels.llm_tokens_per_second, labels.gpu_temperature_c, labels.gpu_power_w
| SORT @timestamp DESC | LIMIT 20

-- GPU utilisation across training cluster
FROM metrics-*
| WHERE metricset.name == "app" AND service.name == "smoke-tier-d-dcgm-exporter"
| KEEP @timestamp, labels.gpu_index, labels.dcgm_gpu_util_pct,
       labels.dcgm_temp_c, labels.dcgm_power_w, labels.dcgm_tensor_active
| SORT @timestamp DESC | LIMIT 40
```

---

## Signals sent by every test

Each smoke test emits all three OTel signal types:

| Signal | What | Example attributes |
|--------|------|--------------------|
| **Traces** | Spans for each operation with business context | `order.id`, `customer.tier`, `payment.amount_usd` |
| **Logs** | Structured log records correlated to spans via `trace.id` | `llm.tokens_per_second`, `gpu.temperature_c` |
| **Metrics** | Counters + histograms for rates and distributions | `checkout.requests`, `hw.gpu.utilization` |

---

## Verify in Kibana

```
Observability → APM → Services       filter: service.name: smoke-*
Observability → Logs                 filter: service.name: smoke-*
Observability → APM → Service Map    (cross-tier shows 4 connected nodes)
```

**ES|QL quick checks:**
```sql
-- All smoke test spans (last 30 min)
FROM traces-apm*
| WHERE service.name LIKE "smoke-*"
| KEEP @timestamp, service.name, transaction.name, labels.customer_tier
| SORT @timestamp DESC | LIMIT 50

-- GPU observability
FROM traces-apm*
| WHERE service.name IN ("smoke-tier-c-cuda-nvml", "smoke-tier-d-dcgm-exporter")
| KEEP @timestamp, service.name, span.name, labels.gpu_utilization_pct,
       labels.llm_model, labels.llm_tokens_per_second
| SORT @timestamp DESC | LIMIT 20

-- Cross-tier trace (all 4 tiers, same trace_id)
FROM traces-apm*
| WHERE service.name IN ("activation-api", "legacy-billing-engine",
                         "payment-gateway-stripe", "notification-sms-bash")
| KEEP @timestamp, service.name, transaction.name, trace.id
| SORT @timestamp DESC | LIMIT 20
```

---

## Enable ES content verification

By default `06-verify/check_spans.py` only pings the OTLP endpoint (HTTP 200).
To also query span content from Elasticsearch:

1. Kibana → Stack Management → Security → API Keys → Create API Key
2. Index privilege: `traces-apm*` → `read`
3. Add to `.env`:
   ```
   ELASTIC_ES_READ_API_KEY=<your-key>
   ```

---

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| **All Python tests** | `pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http` |
| **Node.js test** | Node.js 18+ — `cd 02-tier-a-nodejs && npm install` |
| **Perl test** | `cpan install LWP::UserAgent JSON` |
| **Sidecar (Tier D)** | Python 3 + OTel SDK (started automatically by `run-all.sh`) |
| **Real GPU (optional)** | `pip install nvidia-ml-py` + NVIDIA GPU + CUDA driver |
| **Docker** | Docker + Docker Compose (for `docker compose` commands) |

---

## Project structure

```
smoke-tests/
├── .env.example              ← Copy → .env, fill credentials
├── run-all.sh                ← Run all 53 tests locally
├── runner.sh                 ← Used by Docker runner container
├── Dockerfile                ← Python runner image (OTel deps pre-baked)
├── docker-compose.yml        ← Full suite with profiles
├── o11y_bootstrap.py         ← Shared helper: TracerProvider + LoggerProvider + MeterProvider
│
├── 01-tier-a-python/         ← Tier A: Python
├── 02-tier-a-nodejs/         ← Tier A: Node.js
├── 08-tier-a-java/           ← Tier A: Java  (smoke.java + smoke.py runner)
├── 09-tier-a-go/             ← Tier A: Go    (smoke.go  + smoke.py runner)
├── 10-tier-a-ruby/           ← Tier A: Ruby  (smoke.rb  + smoke.py runner)
├── 11-tier-a-dotnet/         ← Tier A: .NET  (smoke.cs  + smoke.py runner)
├── 12-tier-a-php/            ← Tier A: PHP   (smoke.php + smoke.py runner)
│
├── 03-tier-b-manual-wrap/    ← Tier B: Flask
├── 13-…19-tier-b-*/          ← Tier B: Django / Tornado / Bottle / Falcon / aiohttp / Celery
│
├── 04-tier-c-monkey-patch/   ← Tier C: Stripe
├── 20-…32-tier-c-*/          ← Tier C: Twilio / SendGrid / boto3 / Redis / Mongo / psycopg2 …
├── 51-tier-c-cuda-nvml/      ← Tier C: NVIDIA GPU (nvidia-ml-py)  ★
│
├── 05-tier-d-sidecar/        ← Tier D: Bash + Perl + Python sidecar clients
├── 33-…50-tier-d-*/          ← Tier D: COBOL / PowerShell / SAP / RPG / MATLAB / R / Lua …
├── 52-tier-d-dcgm-exporter/  ← Tier D: NVIDIA DCGM multi-GPU training  ★
│
├── 07-cross-tier-full-o11y/  ← Cross-tier: A→B→C→D, shared trace_id
└── 06-verify/                ← OTLP ping + ES query verification
    └── check_spans.py
```
