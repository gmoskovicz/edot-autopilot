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

## Platform coverage

**Legacy runtimes (Tier D)** — [`otel-sidecar/`](otel-sidecar/README.md) is a tiny HTTP server at `localhost:9411`. Any process that can make an HTTP POST (COBOL, SAP ABAP, IBM RPG, Bash, PowerShell) emits spans to Elastic with no SDK and no binary changes.

**Kubernetes** — add one pod annotation; the [OTel Operator](https://github.com/open-telemetry/opentelemetry-operator) injects the agent automatically (`inject-python`, `inject-java`, `inject-nodejs`, `inject-dotnet`). For Tier D pods, run the sidecar as a second container in the same pod.

**AWS Lambda** — use the [ADOT Lambda layer](https://aws-otel.github.io/docs/getting-started/lambda) with an `otlphttp` exporter pointing at your Elastic endpoint.

**NVIDIA GPU / CUDA** — two smoke tests cover GPU workloads: `51-tier-c-cuda-nvml` monkey-patches `nvidia-ml-py` for LLM inference traces and `hw.gpu.*` metrics; `52-tier-d-dcgm-exporter` covers the DCGM → Collector → Elastic pipeline for multi-GPU training jobs.

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

| Directory | Purpose |
|---|---|
| `observability-edot-autopilot/` | AI skill package — drop-in for Claude Code, Cursor, Copilot, Gemini CLI, and any agentskills.io-compatible agent |
| `CLAUDE.md` | Claude Code–specific version — drop into any repo root and run `Observe this project.` |
| `otel-sidecar/` | Universal Tier D bridge — HTTP server that translates legacy HTTP POSTs into OTLP spans |
| `smoke-tests/` | 86 eval tests across all 4 tiers and 65+ technologies (single-language → multi-service → mobile → E2E) |
| `tests/integration/` | Real SDK integration tests — Java, Node.js, Python running in Docker against a local OTel Collector |
| `docs/` | Per-language OpenTelemetry guides for runtimes no other tool covers (COBOL, SAP ABAP, IBM RPG, Perl, PowerShell…) |
| `tools/` | `otel-contracts.py` — CLI validator for telemetry contracts in CI |

---

## How much does "Observe this project." cost?

This is a one-time cost — paid once when you instrument the project, not on every deploy or run.

### What drives the cost

An agentic `claude -p` run is a multi-turn conversation. Three things determine how many tokens are consumed:

1. **CLAUDE.md** — ~8,000 tokens, loaded as context on every turn (prompt-cached after the first at ~10× discount)
2. **File reads** — Claude reads entry points, imported modules, config files, and business logic files selectively. It does not read the entire codebase. Typical read surface: 5–15% of total LOC.
3. **Conversation history** — the largest driver. Each turn appends the previous turn's output to the input. A 20-turn session with a 30K-token history means ~600K total input tokens — even if the underlying codebase is small.

### Cost by lines of code (claude-sonnet-4-6)

Pricing: $3 / 1M input tokens · $15 / 1M output tokens (as of early 2026)

| LOC | Sonnet 4.6 | Haiku 4.5 | Opus 4.6 |
|-----|-----------|-----------|----------|
| 200 | ~$0.65 | ~$0.17 | ~$3.25 |
| 500 | ~$1.00 | ~$0.27 | ~$5.00 |
| 1,000 | ~$1.30 | ~$0.35 | ~$6.50 |
| 2,000 | ~$1.65 | ~$0.44 | ~$8.25 |
| 5,000 | ~$2.10 | ~$0.56 | ~$10.50 |
| 10,000 | ~$3.20 | ~$0.85 | ~$16.00 |
| 30,000 | ~$4.50 | ~$1.20 | ~$22.50 |
| 100,000 | ~$8.00 | ~$2.13 | ~$40.00 |
| 200,000 | ~$10.70 | ~$2.85 | ~$53.50 |

> Multi-language or multi-service projects cost ~20–50% more than single-service projects of the same LOC, because reconnaissance requires more turns to map cross-service flows.

### Formula

Cost scales with LOC at roughly **LOC^0.4** — not linearly. Doubling the codebase doesn't double the cost because Claude reads selectively (~10–15% of total files).

```
cost_usd = 0.08 × LOC^0.4          # claude-sonnet-4-6
cost_usd = 0.021 × LOC^0.4         # claude-haiku-4-5  (÷ 3.75)
cost_usd = 0.40 × LOC^0.4          # claude-opus-4-6   (× 5)
```

Example — 6,200 LOC Node.js + React Native + scraper project:
```
0.08 × 6200^0.4 = 0.08 × 28.7 ≈ $2.30  (Sonnet)
```

### Model comparison

| Model | vs Sonnet | When to use |
|---|---|---|
| **claude-haiku-4-5** | ÷ 3.75 | Simple, well-structured single-language codebases |
| **claude-sonnet-4-6** | baseline | Recommended for most projects |
| **claude-opus-4-6** | × 5 | Legacy codebases with poor naming, deep call graphs, Tier D components |

### How to cap and measure

**Cap spending** — pass `--max-budget-usd` to the Claude Code CLI:
```bash
claude --dangerously-skip-permissions -p "Observe this project. ..." \
  --model claude-sonnet-4-6 \
  --max-budget-usd 5.00
```

**Measure actual cost** — after the run, the Claude Code CLI prints the total cost. Historical usage is in the [Anthropic console](https://console.anthropic.com) under Usage.

**Reduce cost for large projects:**
- Run on a feature branch with only the services you want to instrument (not the full monorepo)
- Tell Claude which files to focus on: `Observe this project. Focus on the checkout flow in api/orders.py and the fraud module.`
- Use `--model claude-haiku-4-5` for a first pass; follow up with Sonnet for enrichment

---

## Language guides

Per-language OpenTelemetry guides for runtimes that every other tool ignores:

| Language / Runtime | Guide |
|---|---|
| COBOL (mainframe batch) | [opentelemetry-cobol.md](docs/opentelemetry-cobol.md) |
| Perl (AIX, legacy Linux) | [opentelemetry-perl.md](docs/opentelemetry-perl.md) |
| Bash / shell scripts | [opentelemetry-bash-shell-scripts.md](docs/opentelemetry-bash-shell-scripts.md) |
| PowerShell | [opentelemetry-powershell.md](docs/opentelemetry-powershell.md) |
| Classic ASP / VBScript | [opentelemetry-classic-asp-vbscript.md](docs/opentelemetry-classic-asp-vbscript.md) |
| .NET Framework 4.x | [opentelemetry-dotnet-framework-4x.md](docs/opentelemetry-dotnet-framework-4x.md) |
| Python 2.7 | [opentelemetry-python2.md](docs/opentelemetry-python2.md) |
| SAP ABAP | [opentelemetry-sap-abap.md](docs/opentelemetry-sap-abap.md) |
| IBM RPG / AS400 | [opentelemetry-ibm-rpg.md](docs/opentelemetry-ibm-rpg.md) |
| Legacy runtimes (overview) | [opentelemetry-legacy-runtimes.md](docs/opentelemetry-legacy-runtimes.md) |

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

### How do I add OpenTelemetry to SAP ABAP?

SAP ABAP has no official OTel SDK. The approach: add a small utility class (`ZCL_OTEL_SIDECAR`) to your ABAP system that wraps HTTP calls to the telemetry sidecar. The sidecar runs as a Docker container or process on a Linux host the SAP Application Server can reach. ABAP programs call `ZCL_OTEL_SIDECAR=>emit_event()` after business operations — sales order creation, delivery processing, FI postings, batch job steps. All calls are fire-and-forget inside a `CATCH cx_root` block, so telemetry failures can never impact business processes. See the [complete SAP ABAP guide](docs/opentelemetry-sap-abap.md).

### How do I add OpenTelemetry to IBM RPG (AS/400)?

IBM RPG programs can emit telemetry via shell-out to `curl` using `QSYS/QCMDEXC`, or via the IBM i HTTP APIs on newer releases. The sidecar runs on a Linux host or Docker container on the same network as the IBM i system; RPG programs call it by IP address. For batch RPG jobs that run for minutes, use `OtelStartSpan` / `OtelEndSpan` pairs to capture real duration. CL procedures can emit telemetry the same way. See the [complete IBM RPG guide](docs/opentelemetry-ibm-rpg.md).

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
