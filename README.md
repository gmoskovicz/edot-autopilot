# EDOT Autopilot — OpenTelemetry Autopilot for Any Codebase (Including COBOL, Perl, and Legacy Runtimes)

[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-compatible-blue?logo=opentelemetry)](https://opentelemetry.io)
[![Elastic EDOT](https://img.shields.io/badge/Elastic-EDOT-005571?logo=elastic)](https://www.elastic.co/docs/reference/opentelemetry)
[![Agent Skill](https://img.shields.io/badge/Agent%20Skill-agentskills.io-8A2BE2)](https://agentskills.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/languages-65%2B-brightgreen)](smoke-tests/README.md)
[![CI](https://github.com/gmoskovicz/edot-autopilot/actions/workflows/smoke-tests.yml/badge.svg)](https://github.com/gmoskovicz/edot-autopilot/actions/workflows/smoke-tests.yml)

**EDOT Autopilot** is an OpenTelemetry autopilot for any language — modern or legacy — powered by Elastic EDOT, with full support for runtimes that have no OTel SDK.

---

## Why this exists

Every APM vendor supports Python, Java, Node.js, and .NET. Add the agent, restart the process, done.

That works for greenfield services. It doesn't work for the COBOL batch job that processes payroll, the Perl script running on AIX, or the Python 2.7 monolith nobody has touched since 2016. Those systems often carry the most business risk — and they have zero observability, because every tool quietly stops where the SDK support ends.

**This project doesn't stop there.**

For languages with no OpenTelemetry SDK, it generates a telemetry sidecar — a tiny HTTP bridge the legacy process calls with a simple POST. No SDK. No upgrade. No rewrite. The COBOL job emits a span. The Perl script emits a span. They appear in Elastic APM alongside your modern services, in the same trace, with the same SLOs applied.

The other thing generic agents don't do: read your code before instrumenting it. They instrument what the SDK can detect — HTTP calls, DB queries, framework hooks. They don't know that `POST /api/v1/txn` is a payment authorization, that `fraud_score` is the field ops needs during an incident, or that the slow path through your checkout flow costs $40k/hour when it degrades. This project reads first. The spans it generates carry order values, customer tiers, and fraud decisions — not just status codes.

> **If you have a language in your stack that no other tool supports, this was built for you.**

---

## Use with any AI coding assistant

EDOT Autopilot is packaged as a standard [agentskills.io](https://agentskills.io) skill. Install it once and it works across **Claude Code, Cursor, GitHub Copilot, Gemini CLI, Windsurf, Roo, Cline, and Codex** — any agent that follows the open skill specification.

```bash
npx skills add gmoskovicz/edot-autopilot/observability-edot-autopilot
```

Then tell your AI coding assistant:

```
Observe this project.
My Elastic endpoint: https://<deployment>.apm.<region>.cloud.es.io
My API key: <key>
```

The agent reads the codebase, assigns each component to the right instrumentation tier, generates working OTel code for every language it finds — including the ones with no SDK — and verifies that telemetry is flowing in Elastic before it stops.

**Skill package contents** (`observability-edot-autopilot/`):

| File | Purpose |
|------|---------|
| `SKILL.md` | Agent-agnostic instructions (5 phases, under 500 lines) |
| `references/semconv-conventions.md` | **OTel semconv cheatsheet** — correct attribute names, SpanKind rules, metric naming, CWV, exception handling. Agents read this to generate correct code first-time. |
| `references/tier-guide.md` | Full code for Tier A–C across Python, Java, Node.js, Go, .NET |
| `references/sidecar-callers.md` | Copy-paste snippets: COBOL, Perl, Bash, PowerShell, Classic ASP, PHP 5, Ruby |
| `references/enrichment-patterns.md` | Business span attributes, span events, span links, observable gauges, Core Web Vitals |
| `scripts/o11y_bootstrap.py` | Python 3-signal helper (traces + logs + metrics in one call) |
| `scripts/otel-sidecar.py` | HTTP-to-OTLP bridge for legacy runtimes |
| `assets/docker-compose-sidecar.yml` | Tier D Docker deployment with healthcheck |

> Not using an AI assistant? Drop [`CLAUDE.md`](CLAUDE.md) into any repo root for the same workflow in Claude Code specifically.

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
| **Metrics** | Counters + histograms + gauges — `checkout.requests`, `hw.gpu.utilization`, `auth.active_sessions` |

---

## The four-tier coverage model

No other tool has a graceful degradation strategy that covers every runtime ever built.

| Tier | Strategy | When to use | Examples |
|------|----------|-------------|---------|
| **A** — OTel SDK (direct) | App imports OTel SDK directly — upstream or EDOT distribution | New services, greenfield, any platform with an OTel SDK | Python, Node.js, Java, Go, Ruby, .NET, PHP, iOS (Swift), Android (Kotlin) |
| **B** — Manual span wrapping | Decorator/wrapper at startup | Frameworks without auto-instrumentation | Django ORM, Flask raw, Tornado, Bottle, Falcon |
| **C** — Library monkey-patch | Patch third-party SDK at import | All call sites covered in one place | Stripe, Twilio, boto3, Redis, OpenAI, CUDA |
| **D** — HTTP sidecar bridge | Curl/HTTP to a local OTel proxy | No SDK exists for the runtime | COBOL, SAP ABAP, IBM RPG, PowerShell, MATLAB |

> **Every existing tool stops at Tier B and says "unsupported."**
> This one generates working instrumentation for Tier D — anything that can make an HTTP call.

---

## Test suite

82 real-world eval tests. Each one starts with a blank, uninstrumented app, runs `claude -p "Observe this project."`, and verifies that the agent correctly instruments it — right packages, right tier, right business attributes — then starts the app and confirms it runs. No simulations, no hardcoded expected output. See [`smoke-tests/`](smoke-tests/) for the full list.

---

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/gmoskovicz/edot-autopilot.git
cd edot-autopilot
cp .env.example .env
# Fill in ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY

# 2. Run all smoke tests (Python only — no other runtimes needed)
cd smoke-tests
pip install -r requirements.txt
bash run-all.sh

# 3. Run real SDK integration tests (Java + Node.js + Python in Docker, no Elastic needed)
bash ../tests/integration/run.sh
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

## Kubernetes: zero-touch instrumentation with the OTel Operator

For cloud-native services running in Kubernetes, the
[OpenTelemetry Operator](https://github.com/open-telemetry/opentelemetry-operator)
can auto-inject instrumentation into pods without touching application code at all.

### Install the operator

```bash
kubectl apply -f https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml
```

### Create an Instrumentation resource pointing at Elastic

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: edot-instrumentation
  namespace: default
spec:
  exporter:
    endpoint: https://<deployment>.apm.<region>.cloud.es.io
  env:
    - name: OTEL_EXPORTER_OTLP_HEADERS
      valueFrom:
        secretKeyRef:
          name: elastic-otel-secret
          key: headers
  propagators:
    - tracecontext
    - baggage
    - b3
  sampler:
    type: parentbased_traceidratio
    argument: "1.0"
  python:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:latest
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:latest
  nodejs:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-nodejs:latest
  dotnet:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-dotnet:latest
```

### Annotate your deployments — no code changes needed

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-python-api
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-python: "true"
        # For Java:  instrumentation.opentelemetry.io/inject-java: "true"
        # For Node:  instrumentation.opentelemetry.io/inject-nodejs: "true"
        # For .NET:  instrumentation.opentelemetry.io/inject-dotnet: "true"
```

The operator injects the EDOT agent as an init container. Your pod restarts once
and begins sending traces, metrics, and logs to Elastic — zero application changes.

For legacy workloads in Kubernetes that the operator cannot inject (Tier D),
run the `otel-sidecar` as a sidecar container in the same pod:

```yaml
containers:
  - name: legacy-app
    image: my-legacy-app
  - name: otel-sidecar
    image: gmoskovicz/edot-autopilot-sidecar:latest
    env:
      - name: OTEL_SERVICE_NAME
        value: legacy-app
    envFrom:
      - secretRef:
          name: elastic-otel-secret
```

---

## AWS Lambda: serverless observability

AWS Lambda has official OTel support via the
[AWS Distro for OpenTelemetry (ADOT) Lambda layer](https://aws-otel.github.io/docs/getting-started/lambda).
Configure it to send directly to Elastic:

```bash
# Add the ADOT layer to your Lambda function
aws lambda update-function-configuration \
  --function-name my-function \
  --layers arn:aws:lambda:<region>:901920570463:layer:aws-otel-python-<arch>-ver-1-x-x:1

# Set environment variables
aws lambda update-function-configuration \
  --function-name my-function \
  --environment "Variables={
    OPENTELEMETRY_COLLECTOR_CONFIG_URI=/var/task/collector.yaml,
    OTEL_SERVICE_NAME=my-lambda-function,
    OTEL_DEPLOYMENT_ENVIRONMENT=production
  }"
```

**`collector.yaml`** (bundled with your Lambda deployment package):

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: localhost:4317

exporters:
  otlphttp:
    endpoint: https://<deployment>.apm.<region>.cloud.es.io
    headers:
      Authorization: "ApiKey <your-api-key>"

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp]
    metrics:
      receivers: [otlp]
      exporters: [otlphttp]
```

**Key Lambda-specific attributes to set:**

```python
span.set_attribute("faas.trigger",        "http")        # or timer/pubsub/datasource
span.set_attribute("faas.invocation_id",  context.aws_request_id)
span.set_attribute("cloud.provider",      "aws")
span.set_attribute("cloud.region",        os.environ["AWS_REGION"])
span.set_attribute("faas.name",           os.environ["AWS_LAMBDA_FUNCTION_NAME"])
span.set_attribute("faas.version",        os.environ["AWS_LAMBDA_FUNCTION_VERSION"])
span.set_attribute("faas.coldstart",      is_cold_start)  # track cold starts explicitly
```

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
                                         (ecommerce shows 9 connected nodes)
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
- **Kibana** — service maps, APM dashboards, ES|QL analytics, Discover, SLO management
- **Elastic Cloud Serverless** — zero-ops deployment; OTLP ingest endpoint ready out of the box
- **Elastic Cloud on Kubernetes (ECK)** — self-managed; same OTLP endpoint, full data control
- **OpenTelemetry Collector** — drop-in for teams that need a collector tier; configure the `otlphttp` exporter to point at your Elastic endpoint, all pipelines work unchanged
- **OTel Collector contrib receivers** — `prometheusreceiver`, `hostmetricsreceiver`, `dockerstatsreceiver` all forward to Elastic via the same OTLP/HTTP pipeline this project uses
- **Elastic Fleet + EDOT managed agents** — for teams using Fleet-managed instrumentation alongside this project; both write to the same APM indices
- **GitHub Actions** — three-job CI pipeline: syntax check (every PR, no credentials), smoke tests (push to main + nightly, uses Elastic secrets), integration tests (every PR, Docker-only, no credentials)
- **Docker** — full suite runs in a single `docker compose up` with no local runtimes required; integration tests run entirely in containers with a local OTel Collector
- **Claude Code · Cursor · GitHub Copilot · Gemini CLI · Windsurf · Roo · Cline · Codex** — via the agentskills.io skill package

---

## Repository structure

```
edot-autopilot/
│
├── observability-edot-autopilot/     # AI skill package (agentskills.io spec)
│   ├── SKILL.md                      #   Agent-agnostic instructions for all coding assistants
│   ├── references/
│   │   ├── semconv-conventions.md    #   OTel semconv cheatsheet — agents read this first
│   │   ├── tier-guide.md             #   Full code for Tier A–C (Python, Java, Node, Go, .NET)
│   │   ├── sidecar-callers.md        #   COBOL, Perl, Bash, PowerShell, Classic ASP snippets
│   │   └── enrichment-patterns.md   #   Span events, observable gauges, span links, CWV
│   ├── scripts/                      #   o11y_bootstrap.py + otel-sidecar.py
│   └── assets/                       #   Docker Compose + .env template
│
├── CLAUDE.md                         # Claude Code–specific version (drop into any repo)
├── llms.txt                          # LLM-readable project summary (agentskills.io standard)
├── README.md                         # This file
├── .env.example                      # Credentials template
│
├── otel-sidecar/                     # Universal Tier D bridge (traces + logs + metrics)
│   ├── otel-sidecar.py
│   ├── Dockerfile
│   └── README.md
│
├── smoke-tests/                      # 82 smoke tests — all 4 tiers, 65+ technologies
│   ├── run-all.sh                    #   Run everything locally
│   ├── requirements.txt              #   All Python dependencies for the suite
│   ├── docker-compose.yml            #   Full suite with Docker profiles
│   ├── o11y_bootstrap.py             #   Shared helper: tracer + logger + meter
│   │
│   ├── 01-tier-a-python/             #   Tier A: Python (real SDK)
│   ├── 02-tier-a-nodejs/             #   Tier A: Node.js (real SDK, multi-service, 25 scenarios)
│   ├── 08–12-tier-a-*/               #   Tier A: Java / Go / Ruby / .NET / PHP (instrumentation pattern tests)
│   ├── 03,13–19-tier-b-*/            #   Tier B: Flask / Django / Tornado / Bottle …
│   ├── 04,20–32,51-tier-c-*/         #   Tier C: Stripe / Twilio / boto3 / CUDA …
│   ├── 05,33–52-tier-d-*/            #   Tier D: COBOL / SAP / MATLAB / DCGM …
│   ├── 07-cross-tier-full-o11y/      #   A→B→C→D with shared trace_id
│   ├── 06-verify/                    #   OTLP ping + ES content verification
│   │
│   ├── 60-ecommerce/                 #   9-service checkout platform (30 scenarios)
│   ├── 61-auth-platform/             #   7-service auth stack (25 scenarios)
│   ├── 62-data-pipeline/             #   7-service ETL pipeline (14 scenarios)
│   ├── 63-ml-inference/              #   7-service ML serving (25 scenarios)
│   ├── 64-saas-ops/                  #   7-service SaaS platform (25 scenarios)
│   ├── 65–70-mobile-*/              #   Mobile: React Native / Flutter / iOS / Android / MAUI / Ionic
│   ├── 71–75-web-*/                 #   Web RUM: React / Next.js / Vue / Angular / Svelte
│   ├── 76–80-web-*/                 #   Backends: NestJS / Gin / Rails / FastAPI / HTMX
│   ├── 81-mobile-ecommerce/         #   9-service mobile e-commerce scenario
│   └── 82–85-e2e-*/                 #   E2E workflow verification (real apps, InMemory + Elastic)
│
├── tests/
│   └── integration/                  # Real SDK tests — Java + Node.js + Python in Docker
│       ├── docker-compose.yml        #   Collector + real app containers
│       ├── otel-collector-config.yml #   File exporter (no Elastic credentials needed)
│       ├── validate.py               #   Parses collector JSONL, asserts span shapes
│       └── run.sh                    #   Build → start → traffic → validate → teardown
│
└── docs/                             # Per-language OpenTelemetry guides (SEO pages)
    ├── opentelemetry-cobol.md
    ├── opentelemetry-perl.md
    ├── opentelemetry-bash-shell-scripts.md
    ├── opentelemetry-powershell.md
    ├── opentelemetry-classic-asp-vbscript.md
    ├── opentelemetry-dotnet-framework-4x.md
    ├── opentelemetry-python2.md
    ├── telemetry-sidecar-pattern.md
    └── business-span-enrichment.md
```

---

## Frequently Asked Questions

### How do I add OpenTelemetry to a language without an SDK?
Use the Tier D telemetry sidecar pattern. EDOT Autopilot generates a lightweight Python HTTP server that runs alongside your application. Any language that can make an HTTP POST call — COBOL, Perl, Bash, PowerShell, VBScript — can send traces, logs, and metrics to it. The sidecar translates these to OTLP and forwards them to Elastic. No SDK required. Ready-to-paste caller snippets for every language are in [`observability-edot-autopilot/references/sidecar-callers.md`](observability-edot-autopilot/references/sidecar-callers.md).

### How do I instrument a COBOL application with OpenTelemetry?
Install the skill (`npx skills add gmoskovicz/edot-autopilot/observability-edot-autopilot`) and tell your AI coding assistant: `Observe this project. My Elastic endpoint: <url>. My API key: <key>`. The agent reads your COBOL source, identifies the business-critical batch jobs and CALL statements, generates a Python sidecar server, and produces COBOL `CALL` snippets using `libcurl` (or the HTTP facility in your COBOL environment) that POST span data to the sidecar. Your COBOL program then appears in the Elastic APM service map alongside your modern services.

### How do I add observability to a legacy .NET Framework application?
Legacy .NET Framework 4.x has partial upstream OTel SDK support. EDOT Autopilot handles it via Tier B (manual span wrapping around key service methods) or Tier D (sidecar) for older versions. The smoke test in `11-tier-a-dotnet/` demonstrates the pattern. Full .NET Framework 4.x wrapping code is in [`observability-edot-autopilot/references/tier-guide.md`](observability-edot-autopilot/references/tier-guide.md).

### What is the difference between EDOT and the upstream OpenTelemetry collector?
EDOT (Elastic Distribution of OpenTelemetry) is Elastic's production-hardened distribution of the OTel SDK and collector, pre-configured for the Elastic stack. Unlike the upstream collector, EDOT ships with Elastic-specific processors (APM correlation, service map topology), default exporters for Elastic Cloud, and agent management via Fleet. This project uses EDOT's OTLP HTTP endpoint directly — no collector process required.

### How do I send OpenTelemetry data directly to Elastic without a collector?
Create an API key in Elastic Cloud → Stack Management → API Keys, set the `Authorization: ApiKey <key>` header, and point your OTLP exporter at `https://<deployment>.apm.<region>.cloud.es.io`. The `o11y_bootstrap.py` helper handles this for all three signal types (traces, logs, metrics) in one call. See [`assets/.env.otel.example`](observability-edot-autopilot/assets/.env.otel.example) for the full variable reference.

### How do I add business context to OpenTelemetry spans?
Use `span.set_attribute("order.value_usd", 249.99)` for any data with business meaning. Standard auto-instrumentation captures `http.status_code=200`. Business-enriched instrumentation captures `customer.tier=enterprise`, `fraud.score=0.23`, `payment.method=amex`, `order.items_count=3`. See [`observability-edot-autopilot/references/enrichment-patterns.md`](observability-edot-autopilot/references/enrichment-patterns.md) for patterns across e-commerce, auth, ML inference, SaaS ops, and data pipeline domains.

### Which AI coding assistants does this work with?
Claude Code, Cursor, GitHub Copilot, Gemini CLI, Windsurf, Roo, Cline, Codex — any agent that supports the [agentskills.io](https://agentskills.io) open skill specification. Install with `npx skills add gmoskovicz/edot-autopilot/observability-edot-autopilot`. For Claude Code specifically, you can also drop [`CLAUDE.md`](CLAUDE.md) directly into your repo root.

### How do I instrument a React Native / Flutter / mobile app with OpenTelemetry?
Mobile apps require platform-specific OTel resource attributes (`device.model.name`, `device.manufacturer`, `os.type`, `os.version`, `os.build_id`, `app.version`, `telemetry.sdk.name`) plus session and network context. The smoke tests in `65–70` demonstrate full 3-signal instrumentation for React Native, Flutter, iOS Swift, Android Kotlin, .NET MAUI, and Ionic/Capacitor — each with crash reporting, biometric auth flows, and push notification correlation. Use the `extra_resource_attrs` parameter in `o11y_bootstrap.py` to inject platform attributes at the OTel Resource level (semantically correct per spec). Note: `device.id` carries GDPR implications — the examples SHA-256 hash it.

### How do I instrument browser RUM and Core Web Vitals with OpenTelemetry?
The smoke tests in `71–75` cover React SPA, Next.js, Vue, Angular, and SvelteKit. Each emits Core Web Vitals as OTel histograms with bucket boundaries aligned to Google's Good/Needs Improvement/Poor thresholds. Use **INP** (Interaction to Next Paint) — Chrome deprecated FID in March 2024. Metrics: `webvitals.lcp`, `webvitals.inp`, `webvitals.cls`, `webvitals.ttfb`, `webvitals.fcp`. Set `browser.name`, `browser.version`, `browser.platform`, `browser.mobile`, and `user_agent.original` as resource attributes for proper segmentation in Kibana.

### How do I instrument OpenAI, Anthropic, or AWS Bedrock calls with OpenTelemetry?

Use the `gen_ai.*` semantic conventions. The required span attributes are
`gen_ai.system` (e.g. `openai`, `anthropic`, `aws.bedrock`), `gen_ai.operation.name`
(`chat`, `text_completion`, `embeddings`), and `gen_ai.request.model`. After the call,
set `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and
`gen_ai.response.finish_reasons`. Never log raw prompt or completion content —
use content hashes for debugging. See smoke test 89 for a complete working example
covering all three providers.

### How do I use the correct OTel semantic convention attribute names?
OTel stabilized new HTTP and database attribute names in semconv 1.20–1.22. Many examples online still use the deprecated names. Quick rules: `http.method` → `http.request.method`, `http.status_code` → `http.response.status_code`, `http.url` → `url.full`, `db.system` → `db.system.name`, `db.statement` → `db.query.text`, `db.operation` → `db.operation.name`. OTel counters never include `_total` (the Prometheus exporter adds it on export). Always set `service.peer.name` on CLIENT spans — Elastic APM service maps require it to draw edges between services. The full cheatsheet is at [`observability-edot-autopilot/references/semconv-conventions.md`](observability-edot-autopilot/references/semconv-conventions.md).

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) to add a new language caller snippet (30-minute contribution)
or a new multi-service scenario. New Tier D languages are especially welcome — see the wishlist there.

---

## Built on

- [Elastic EDOT](https://www.elastic.co/docs/reference/opentelemetry) — Elastic Distributions of OpenTelemetry
- [OpenTelemetry](https://opentelemetry.io/) — vendor-neutral observability standard
- [agentskills.io](https://agentskills.io) — open AI agent skill specification
- [elastic/agent-skills](https://github.com/elastic/agent-skills) — Elastic's skill library
- [OTel Hardware semconv](https://opentelemetry.io/docs/specs/semconv/hardware/gpu/) — `hw.gpu.*` GPU metrics
- [NVIDIA DCGM Exporter](https://github.com/NVIDIA/dcgm-exporter) — GPU cluster monitoring

---

> **Repo topics to add** (improves GitHub discoverability):
> `opentelemetry` `otel` `elastic` `edot` `observability` `tracing` `auto-instrumentation` `cobol` `legacy` `devops` `sre` `apm` `agent-skills` `cursor` `copilot` `kubernetes` `opentelemetry-operator` `k8s`
>
> Set these at: https://github.com/gmoskovicz/edot-autopilot → About → Topics
