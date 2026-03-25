# EDOT Autopilot — Business-Aware Observability for Any Codebase

> **The core insight:** Standard auto-instrumentation shows you that `POST /checkout` took 2.3s.
> Elastic with EDOT Autopilot shows you that a **$4,200 enterprise order failed in the fraud check** for a `high_risk` customer who signed up 2 days ago.
> Same data. Completely different usefulness.

---

## Why this exists

Traditional auto-instrumentation approaches — including standard OpenTelemetry collectors — instrument what they can **detect automatically**: HTTP calls, database queries, framework hooks.

They do not read your code.

They do not know that `POST /api/v1/txn` is a payment authorization. They do not know that `fraud_score` is what ops needs during an incident at 2am. They do not know that the COBOL batch job on a 1998 AIX server is the most critical process in your company.

**Elastic with EDOT Autopilot does.** It reads first. It instruments what matters. And because it runs on Elastic — with ES|QL, machine learning, AIOps, and SLO management built in — the business context it captures flows directly into alerting, anomaly detection, and root cause analysis.

---

## The four-tier coverage model

This is the core novel idea. No tool on the market has a graceful degradation strategy that covers every runtime that has ever existed.

| Tier | Coverage | Strategy | Examples |
|------|----------|----------|---------|
| **A** | Full native EDOT | Zero-config auto-instrumentation | Python, Node.js, Java, .NET 6+, PHP 8+ |
| **B** | Language yes, framework no | Manual SDK span wrapping | .NET Framework 4.x, Python 2.7, old Spring MVC |
| **C** | Language yes, library no | Monkey-patch the library's public API | Stripe SDK, Twilio, legacy SOAP clients |
| **D** | No OTel SDK exists | HTTP sidecar bridge | COBOL, Perl, Bash, PowerShell, SAP ABAP, IBM RPG, Classic ASP, Flutter |

Every existing tool stops at Tier B and says "unsupported." **This one generates working code for Tier D — anything that can make an HTTP call.**

---

## The sidecar: the artifact that makes "any language" real

`otel-sidecar.py` is a universal telemetry bridge. Any process that can make an HTTP POST — which is everything built since the mid-1990s — can now emit spans to Elastic APM.

The legacy process makes simple HTTP calls to `localhost:9411`. The sidecar translates them to OTLP and forwards to Elastic Cloud. Zero changes to the legacy binary.

```
[COBOL on AIX] --curl--> [sidecar:9411] --OTLP--> [Elastic Cloud]
[SAP ABAP]     --http--> [sidecar:9411] --OTLP--> [Elastic Cloud]
[Bash script]  --curl--> [sidecar:9411] --OTLP--> [Elastic Cloud]
[Flutter app]  --http--> [sidecar:9411] --OTLP--> [Elastic Cloud]
```

---

## Phase 1 Reconnaissance: read before you touch

This is what separates this approach from all generic Elastic skills.

Existing skills assume you already know which language to instrument and ask the agent to do it. This one makes the agent **read the code first**, identify what actually matters to the business, and only then instrument — with attributes derived from the source code itself.

The output is a **Reconnaissance Report** that maps business actions to code locations, identifies Golden Paths, and classifies every component by tier before a single line of instrumentation is written.

---

## Phase 3 Business Enrichment: the LinkedIn differentiator

Generic auto-instrumentation gives you:
```
span: POST /api/checkout  http.status_code=500  duration=340ms
```

Business-enriched spans give you:
```
span: checkout.complete
  order.value_usd = 4200.00
  order.item_count = 3
  customer.tier = enterprise
  customer.age_days = 2
  fraud.score = 0.87
  fraud.decision = blocked
  payment.method = wire_transfer
```

The second version is actionable at 2am. The first is not.

---

## Repository structure

```
edot-autopilot/
├── CLAUDE.md                          # Drop into any repo → "Observe this project."
├── README.md                          # This file
├── .env.example                       # Connection variable template
├── otel-sidecar/                      # Universal Tier D bridge
│   ├── otel-sidecar.py
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── README.md
├── tests/
│   ├── tier-a-python-fastapi/         # Native EDOT — Python FastAPI
│   ├── tier-a-nodejs-express/         # Native EDOT — Node.js Express
│   ├── tier-a-java-springboot/        # Native EDOT — Java Spring Boot
│   ├── tier-b-dotnet-framework/       # Manual wrapping — .NET Framework 4.x
│   ├── tier-b-python27/               # Manual wrapping — Python 2.7
│   ├── tier-c-stripe-monkey-patch/    # Library wrap — Stripe SDK
│   ├── tier-d-flutter/                # Sidecar — Flutter (no EDOT support)
│   ├── tier-d-cobol/                  # Sidecar — COBOL
│   ├── tier-d-bash/                   # Sidecar — Bash scripts
│   ├── tier-d-powershell/             # Sidecar — PowerShell
│   ├── tier-d-perl/                   # Sidecar — Perl
│   ├── tier-d-sap-abap/               # Sidecar — SAP ABAP
│   └── tier-d-ibm-as400/              # Sidecar — IBM AS/400 RPG
└── docs/
    ├── tier-model.md
    ├── sidecar-guide.md
    └── business-enrichment.md
```

---

## Quick start

1. Clone this repo
2. Copy `.env.example` → `.env` and fill in your Elastic credentials
3. Pick the test that matches your scenario and follow its README
4. To use CLAUDE.md on your own project:
   ```
   # Drop CLAUDE.md into your project root, then tell Claude Code:
   Observe this project.
   My Elastic endpoint: https://<deployment>.apm.<region>.cloud.es.io
   My Elastic API key: <key>
   ```

---

## Built on

- [Elastic EDOT](https://www.elastic.co/docs/reference/opentelemetry) — Elastic Distributions of OpenTelemetry
- [OpenTelemetry CNCF](https://opentelemetry.io/) — vendor-neutral observability standard
- [elastic/agent-skills](https://github.com/elastic/agent-skills) — Elastic agent skill library
