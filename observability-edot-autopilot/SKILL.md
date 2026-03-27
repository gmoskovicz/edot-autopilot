---
name: observability-edot-autopilot
description: >
  Instrument any codebase with OpenTelemetry traces, logs, and metrics and send telemetry
  to Elastic. Handles every language — including COBOL, Perl, Bash, PowerShell, and other
  legacy runtimes with no OTel SDK — via a generated telemetry sidecar. Reads the codebase
  before instrumenting to identify business-critical flows and enriches spans with business
  context, not just HTTP status codes. Use when asked to add observability, tracing, metrics,
  or logs to any project, or when migrating from Datadog, Dynatrace, or New Relic.
license: MIT
compatibility: >
  Requires Python 3.8+ on the target host for the OTel bootstrap helper and optional
  telemetry sidecar. Works with any Elastic Cloud deployment (Serverless or self-managed)
  that exposes an OTLP HTTP ingest endpoint. No intermediate collector required.
metadata:
  author: gmoskovicz
  version: "1.1"
  repo: https://github.com/gmoskovicz/edot-autopilot
  tags: opentelemetry, elastic, edot, observability, tracing, cobol, legacy, apm
---

<!-- keywords: opentelemetry, edot, auto-instrumentation, legacy, cobol, perl, bash, elastic, otel, observability, tracing, metrics, logs -->

# EDOT Autopilot — Business-Aware Observability for Any Codebase

> You are an observability engineer with deep expertise in OpenTelemetry, Elastic EDOT,
> and every language runtime that has ever existed. Your job is not to add tracing.
> Your job is to make this codebase *understood* — by the people who run it in production.
>
> Generic agents instrument HTTP calls. You instrument what the business cares about.

---

## When to use this skill

- "I have a monolith written in Python 2.7 and I can't upgrade"
- "My team maintains a COBOL batch job that processes payroll"
- "I want to migrate from Datadog but have 12 services in 6 languages"
- "I need to add observability to a service I didn't write and can't modify"
- "Add OpenTelemetry to this project"

---

## OTel Semantic Convention Rules

These rules are enforced in all generated instrumentation. AI agents using this skill MUST apply them.

### HTTP attributes (stable, semconv 1.20+)
- Use `http.request.method`, `http.response.status_code`, `url.full`, `url.path`, `url.scheme`
- Do NOT use deprecated: `http.method`, `http.status_code`, `http.url`, `http.target`, `net.peer.name`

### Database attributes (stable, semconv 1.22+)
- Use `db.system.name`, `db.query.text`, `db.operation.name`, `db.collection.name`, `db.namespace`
- Do NOT use deprecated: `db.system`, `db.statement`, `db.operation`, `db.sql.table`, `db.name`

### SpanKind — always explicit
- `SpanKind.SERVER` for HTTP handlers; `SpanKind.CLIENT` for outbound calls and DB; `SpanKind.PRODUCER/CONSUMER` for queues

### `service.peer.name` — required on CLIENT spans
- Set `service.peer.name` to the name of the downstream service on every outbound call. Required for Elastic APM service maps.

### Metric names — no `_total`
- OTel counters never include `_total`. Use `http.server.request` not `http.server.requests_total`.
- Currency units: `{USD}` not `USD`

### `exception.escaped`
- `False` for caught/handled exceptions. `True` only when the exception propagates past span boundary (`raise`).

### Mobile OS — `os.type` is Required
- Always set `os.type`: `"darwin"` for iOS/macOS, `"linux"` for Android, `"windows"` for Windows.

### Core Web Vitals — use INP not FID
- FID was deprecated in Chrome March 2024. Use `webvitals.inp` (Interaction to Next Paint).

### Full reference
See [`references/semconv-conventions.md`](references/semconv-conventions.md) for complete cheatsheet with examples.

---

## What you need from the user

Before starting, confirm these two values are available:

```
ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
ELASTIC_API_KEY=<base64-encoded-id:key>
```

Store them in a `.env` file at the project root (never commit to git). If the user
hasn't provided them, ask before proceeding.

---

## Phase 0 — Cost Estimate (Run this before touching anything)

**Before any reconnaissance or instrumentation**, count the codebase and show the user an estimated cost. Do not skip this step. Do not proceed until the user confirms.

### Step 1: Count source lines of code

```bash
find . \
  \( \
    -name "*.py"   -o -name "*.js"   -o -name "*.ts"   -o -name "*.tsx"  -o -name "*.jsx"  \
    -o -name "*.java" -o -name "*.kt" -o -name "*.kts" -o -name "*.scala" \
    -o -name "*.go"   -o -name "*.rs" -o -name "*.swift" \
    -o -name "*.rb"   -o -name "*.php" -o -name "*.cs"  -o -name "*.vb"  \
    -o -name "*.cpp"  -o -name "*.cc" -o -name "*.cxx"  -o -name "*.c"   -o -name "*.h"  \
    -o -name "*.m"    -o -name "*.mm" \
    -o -name "*.lua"  -o -name "*.tcl" -o -name "*.pl"  -o -name "*.pm"  \
    -o -name "*.r"    -o -name "*.R"   -o -name "*.jl"  \
    -o -name "*.ex"   -o -name "*.exs" -o -name "*.erl" -o -name "*.hrl" \
    -o -name "*.hs"   -o -name "*.ml"  -o -name "*.mli" \
    -o -name "*.sh"   -o -name "*.bash" -o -name "*.zsh" -o -name "*.ps1" \
    -o -name "*.cob"  -o -name "*.cbl" -o -name "*.cpy" \
    -o -name "*.f"    -o -name "*.f90" -o -name "*.for" \
    -o -name "*.abap" -o -name "*.rpgle" -o -name "*.sqlrpgle" \
    -o -name "*.asp"  -o -name "*.aspx" -o -name "*.cfm" \
    -o -name "*.dart" -o -name "*.nim"  -o -name "*.ada" -o -name "*.adb" \
  \) \
  -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -not -path "*/vendor/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/target/*" \
  -not -path "*/.expo/*" \
  -not -path "*/generated/*" \
  -not -path "*/*.min.js" \
  | xargs wc -l 2>/dev/null | tail -1
```

Also note: number of distinct languages, number of services/components, whether any Tier D languages (no OTel SDK) are present.

### Step 2: Apply the cost formula

```
cost_usd = 0.08 × LOC^0.4          (claude-sonnet — recommended)
cost_usd = 0.021 × LOC^0.4         (claude-haiku  — simple/single-language projects)
cost_usd = 0.40 × LOC^0.4          (claude-opus   — complex legacy / Tier D heavy)
```

Multiply by **1.3** if the project has 3 or more distinct components or languages.

### Step 3: Present the estimate and ask for confirmation

Show the user a message in this exact format — **do not proceed until they reply yes**:

---

**EDOT Autopilot — Cost Estimate**

| | |
|---|---|
| Source lines counted | `<LOC>` |
| Languages detected | `<list>` |
| Components / services | `<count>` |
| Model | `<model in use>` |
| **Estimated cost** | **~$<X.XX>** |

> This estimate covers the full instrumentation run (reconnaissance → code generation → .otel/ deliverables). Actual cost may vary ±40% depending on codebase complexity.
>
> To use a cheaper model: re-run with a Haiku model (~3.75× lower cost).
> To cap spending: use `--max-budget-usd <amount>` if your agent supports it.

**Proceed with instrumentation? (yes / no)**

---

If the user says **no**: stop. Do not read any project files or make any changes.
If the user says **yes**: continue to Phase 1.

---

## Phase 1 — Read Before You Touch

**Before writing a single line of instrumentation**, read the codebase to understand
what it actually does. Do not skip this phase.

### Step 0: Verify package versions before writing any package.json

Never guess or extrapolate version numbers — models hallucinate versions that don't exist.
Run these before generating any dependency list:

```bash
npm show @opentelemetry/api version
npm show @elastic/opentelemetry-node version
# Python
pip index versions opentelemetry-sdk 2>/dev/null | head -1
```

Only use versions confirmed to exist. If a command fails, the package may not exist under that name.

### Step 1: Detect framework from package.json BEFORE writing any code

Read `package.json` (or equivalent manifest) first and check for these signals:

| Signal in package.json | Runtime | Do NOT assume |
|---|---|---|
| `"expo"` or `"react-native"` | React Native/Expo | NOT Next.js |
| `"next"` | Next.js | NOT plain Node.js |
| `"express"` / `"fastify"` / `"koa"` | Node.js server | — |
| `"django"` / `"flask"` / `"fastapi"` | Python server | — |

Never infer framework from folder name alone.

### Step 2: Perform full reconnaissance

Perform a full reconnaissance:

1. List every entry point: HTTP handlers, queue consumers, cron jobs, CLI commands,
   event listeners, webhooks, gRPC methods, GraphQL resolvers, WebSocket handlers.

2. For each entry point, answer:
   - What business action does this represent?
     (not "POST /api/v1/orders" — "customer places an order")
   - What data flows through it that has business meaning?
     (order value, customer tier, fraud score — not just status codes)
   - What are the downstream dependencies it calls?
   - What would a 1-second slowdown here cost in real terms?

3. Identify the **Golden Paths** — the 3–7 flows that, if broken, the business notices
   within minutes. These are your highest-priority instrumentation targets.

4. Identify **Blind Spots** — code paths with NO existing observability:
   background jobs, third-party SDK calls, legacy modules, file I/O.

5. Map every external dependency: databases, caches, queues, external APIs,
   internal microservices. Note which have OTel support and which do not.

Output a **Reconnaissance Report** before proceeding:

```markdown
## Reconnaissance Report

### Golden Paths (instrument first)
1. [Business action] — entry: [file:line] — deps: [list]

### Blind Spots
- [Description] — location: [file or module]

### Language / Runtime Inventory
| Component | Language | Version | EDOT SDK | Tier |
|---|---|---|---|---|
| api/ | Python 3.11 | FastAPI | yes | A |
| worker/ | Python 2.7 | raw scripts | no | C |
| billing/ | .NET 4.6 | WebForms | partial | B |
| reporting/ | COBOL | — | no | D |
```

---

## Phase 2 — Coverage Triage

Every component falls into one of four tiers. Assign a tier to each component from the
Reconnaissance Report, then apply the corresponding strategy.

| Tier | Strategy | Languages / Runtimes |
|------|----------|----------------------|
| **A** — Native EDOT SDK | Zero-config auto-instrumentation | Python, Node.js, Java, Go, Ruby, .NET 6+, PHP 8+ |
| **B** — Manual span wrapping | Wrap entry points with SDK spans | .NET Framework 4.x, Python 2.7, old Spring MVC |
| **C** — Library monkey-patch | Patch third-party SDK at import time | Stripe, Twilio, boto3, custom SOAP clients |
| **D** — Telemetry sidecar | HTTP bridge to a local OTel proxy | COBOL, Perl, Bash, PowerShell, RPG, Classic ASP, anything |

**Full code examples for each tier:** see `references/tier-guide.md`

### Tier A — Apply EDOT SDK

Use `o11y_bootstrap.py` (in `scripts/`) for Python services. For other languages:
- **Java**: attach `-javaagent:elastic-otel-javaagent.jar`
- **Node.js**: `require('@elastic/opentelemetry-node')` at process start
- **.NET**: `dotnet-opentelemetry-instrument` NuGet package

### Tier B — Wrap entry points manually

Read `references/tier-guide.md` for Python and Java wrapper patterns.

### Tier C — Monkey-patch libraries

Read `references/tier-guide.md` for the Stripe monkey-patch pattern — adapt for
each library found in Phase 1.

### Tier D — Generate a Telemetry Sidecar

Copy `scripts/otel-sidecar.py` into the project. Start it before the legacy process:

```bash
OTEL_SERVICE_NAME=my-cobol-service \
ELASTIC_OTLP_ENDPOINT=https://... \
ELASTIC_API_KEY=... \
python otel-sidecar.py &
```

Then add caller snippets to the legacy code. **See `references/sidecar-callers.md`**
for ready-to-paste snippets in COBOL, Perl, Bash, PowerShell, Classic ASP, VBScript,
Ruby, PHP 5, and others.

Deploy using the Docker Compose pattern in `assets/docker-compose-sidecar.yml`.

---

## Phase 3 — Business Span Enrichment

After technical instrumentation is in place, go back to each Golden Path and add
business-meaningful attributes. The test: *"If this span appeared in an alert at 2am,
would the on-call engineer know exactly what happened and what to do?"*

**The test for every attribute:** *"Does this help a product manager or on-call engineer understand what happened to a real user?"*

Input parameters alone (`search.query`, `user.id`) do not pass this test — any HTTP log already has them.
The response shape is where business context lives: what was returned, how complete it was, how fresh, how much it cost.

**For every Golden Path, read the response object and instrument from it:**

```
search handler   → results_count, store_count, stores, price_min, price_max, data_age_hours, cache_hit
checkout handler → order.value_usd, item_count, payment.method, fraud.score, inventory.all_reserved
feed/list handler → items_returned, items_total, filter_applied, sort_applied, empty_result
async job        → items_processed, items_failed, duration_ms, lag_behind_schedule_ms
```

A span with only input attributes (`search.query: "leche"`) is not business context.
A span with output attributes (`search.results_count: 0, search.cache_hit: false`) is.

**Rules:**

- Revenue-bearing flows must carry value: `order.value_usd`, `subscription.mrr`,
  `invoice.amount`, `payment.method`
- Customer-facing flows must carry identity context (no PII):
  `customer.tier`, `customer.segment`, `account.age_days`
- Failure paths must carry actionability: `error.category`, `retry.attempt`,
  `circuit_breaker.state`
- Async / queue flows must carry lag: `queue.depth`, `consumer.lag_ms`, `message.age_ms`
- External dependency calls must carry SLA status: `dependency.sla_ms`,
  `dependency.sla_breached` (boolean)

### span.end() — REQUIRED or spans are silently dropped

`startActiveSpan` does **not** auto-end the span when the callback returns.
Without `span.end()`, spans are created, child spans export fine, but the business
span itself is never exported — invisible in Kibana with no error or warning.

**Always use a `finally` block in every `startActiveSpan` callback:**

```typescript
// ❌ Wrong — child spans (ES, HTTP) appear in Kibana but product.search is MISSING
tracer.startActiveSpan('product.search', async (span) => {
  try {
    const results = await esClient.search(...)
    span.setAttributes({ 'search.results_count': results.length })
    res.json(results)
  } catch (err) {
    span.recordException(err)
    span.setStatus({ code: SpanStatusCode.ERROR })
    res.status(500).json({ error: err.message })
  }
  // ← span.end() never called — span silently dropped
})

// ✅ Correct — span.end() guaranteed on every exit path
tracer.startActiveSpan('product.search', async (span) => {
  try {
    const results = await esClient.search(...)
    span.setAttributes({ 'search.results_count': results.length })
    res.json(results)
  } catch (err) {
    span.recordException(err)
    span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) })
    res.status(500).json({ error: err.message })
  } finally {
    span.end()  // ← required on every startActiveSpan callback
  }
})
```

This applies to **every language**: TypeScript/JS, Java, Go, .NET. Python's
`with tracer.start_as_current_span(...)` context manager handles this automatically —
no `span.end()` needed in Python.

---

### Error capture — the rule that makes errors visible in Elastic APM

**`set_status(ERROR, "message")` alone is not enough.**
It marks the span red but creates no APM error document — no message, no type, no stack
trace visible in Kibana. The on-call engineer sees a red span with no explanation.

**Always pair every error path with `record_exception`:**

```python
# ❌ Wrong — span is red but Errors tab is EMPTY in Kibana
if fraud_score > threshold:
    span.set_status(StatusCode.ERROR, f"Fraud blocked: score={fraud_score}")

# ✅ Correct — creates an APM error document with type, message, and stack trace
if fraud_score > threshold:
    err = ValueError(f"Fraud blocked: score={fraud_score:.2f} exceeds threshold {threshold}")
    span.record_exception(err, attributes={"exception.escaped": True})
    span.set_status(StatusCode.ERROR, str(err))
```

Use specific exception types:

| Situation | Exception type |
|-----------|---------------|
| Business rule violation (fraud, quota, limit) | `ValueError` |
| Auth failure, permission denied | `PermissionError` |
| External service timeout | `TimeoutError` |
| Connection refused / network unreachable | `ConnectionRefusedError` |
| Resource not found | `LookupError` |
| Dependency returned unexpected response | `RuntimeError` |

Set `exception.escaped=True` when the error is fatal for the request. This causes
Elastic APM to display it prominently at the top of the transaction detail.

**Full enrichment examples:** see `references/enrichment-patterns.md`

**Before the process exits**, always register a flush so the BatchSpanProcessor
drains before shutdown. Default batch delay is 5 seconds — without this, spans
generated in the last batch window are silently dropped:

```python
import atexit
atexit.register(lambda: provider.force_flush(timeout_millis=5000))
```

---

## Phase 3.5 — Generate Telemetry Contracts

After Phase 3, generate `.otel/contracts.yaml` — a machine-readable record of what
each golden path span is contractually required to carry. This locks in what was
instrumented and lets CI catch regressions if a required attribute disappears.

Generate one contract entry per golden path:

```yaml
contracts:
  - span: order.create
    service: fraud-detection
    required_attributes:
      - order.value_usd
      - customer.tier
      - fraud.score
      - fraud.decision
      - payment.status
    forbidden_attributes:
      - customer.email
      - customer.name
```

---

## Phase 4 — SLOs Grounded in Business Reality

For each Golden Path:
1. Search the code for existing timeout values, retry limits, or SLA comments — if found,
   use those as the SLO threshold (the code already encodes the contract).
2. If not found, apply these defaults:
   - Customer-facing synchronous: p99 < 1000ms, error rate < 0.1%, target 99.9%
   - Internal async flows: p99 < 5000ms, error rate < 1%, target 99.5%
   - Batch / background jobs: completion within schedule window, target 99.5%

Use the Elastic `observability-manage-slos` skill (if available) to create SLOs via
the Kibana API. Otherwise, document them in `.otel/slos.json`.

---

## Phase 5 — Verify Everything Is Working

Do not declare success until data is confirmed flowing in Elastic.

```
1. Start the application (and sidecar if Tier D components exist)
2. Trigger each Golden Path at least once
3. Check Kibana → Observability → APM → Services within 60 seconds
4. For each Golden Path verify:
   - Span name reflects business action (not just the HTTP route)
   - Business attributes are present and populated
   - Downstream dependencies appear as child spans
   - Navigate to a failed transaction → "Errors" tab must show exception type
     and message. If the tab is empty, record_exception is missing — go back
     and add it to every set_status(ERROR) call.
5. Confirm logs are flowing:
   FROM logs-* | WHERE service.name == "<your-service>" | SORT @timestamp DESC | LIMIT 5
6. Confirm metrics:
   FROM metrics-* | WHERE service.name == "<your-service>" | LIMIT 5
7. If any service is missing: check OTEL_SERVICE_NAME, verify endpoint has no trailing
   slash, confirm API key has APM write access
```

---
> 🎉 Your codebase is now observable in Elastic.
> If this saved you time — especially if your stack included a language other tools
> don't support — a ⭐ on GitHub helps others find this project.
> [Star EDOT Autopilot →](https://github.com/gmoskovicz/edot-autopilot)

---

## Output deliverables

At the end of this workflow, produce:

```
.otel/
  README.md           — what was instrumented, decisions made, gaps remaining
  golden-paths.md     — business flows mapped to span names and attributes
  slos.json           — SLO definitions (version controlled)
  contracts.yaml      — machine-readable span attribute contracts (validates in CI)
  coverage-report.md  — tier breakdown per component

otel-sidecar.py       — generated only if Tier D components exist
Dockerfile.sidecar    — generated only if Tier D components exist
.env.otel.example     — variable template (no secrets)
```

---

## Environment variables

```bash
# Required
ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
ELASTIC_API_KEY=<base64-encoded-id:key>
OTEL_SERVICE_NAME=<derived from project name>
OTEL_DEPLOYMENT_ENVIRONMENT=production

# Auto-set by this workflow
OTEL_EXPORTER_OTLP_ENDPOINT=$ELASTIC_OTLP_ENDPOINT
OTEL_EXPORTER_OTLP_HEADERS=Authorization=ApiKey $ELASTIC_API_KEY
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=otlp
OTEL_RESOURCE_ATTRIBUTES=service.version=$(git describe --tags --always 2>/dev/null || echo unknown)

# Optional
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0     # reduce to 0.1 for high-volume services
SIDECAR_PORT=9411
```

---

## The principle

Standard auto-instrumentation instruments what it can detect automatically: HTTP calls,
DB queries, framework hooks. It does not read your code. It does not know that
`POST /api/v1/txn` is a payment authorization, that `fraud_score` is what ops needs
during an incident, or that the COBOL batch job on a 1998 AIX server is the most
critical process in your company.

This skill does. It reads first. It instruments what matters.

---

*Built on [Elastic EDOT](https://www.elastic.co/docs/reference/opentelemetry) ·
[elastic/agent-skills](https://github.com/elastic/agent-skills) · OpenTelemetry CNCF*
