# OpenTelemetry for Legacy Runtimes — Complete Guide

> Why legacy runtimes are the biggest blind spot in enterprise observability, and how to instrument all of them — from COBOL to Classic ASP — using a single, consistent approach.

## Why legacy runtimes are the biggest blind spot

Enterprise observability tools have a dirty secret: they only instrument what is easy to instrument. Every major APM vendor — Datadog, Dynatrace, New Relic — supports Python 3, Java 11+, Node.js, .NET 6+, Go, and Ruby. Add the agent, restart the process, done.

What they do not tell you is what they skip. And what they skip is often the most important code in the company.

Consider a typical enterprise:
- A COBOL batch job that runs payroll for 40,000 employees every Friday night
- A Perl CGI application that processes supplier invoices
- A Classic ASP portal that handles 30% of customer orders
- A Python 2.7 quant library that prices options for the trading desk
- A PowerShell script that syncs Active Directory to the HR system

None of these will ever have an official APM agent. They are not on any vendor roadmap. They will never be discussed at a developer conference. But they process real money, real customer data, and real business outcomes — and when they fail or slow down, the business notices within minutes.

The observability gap in legacy runtimes is not a niche problem. Gartner estimates that 70% of enterprise applications run on technology more than 10 years old. The OpenTelemetry project formally acknowledges that many runtimes are out of scope for the core specification. COBOL is responsible for an estimated $3 trillion in daily transactions, and no OTel SDK exists for it.

This is what EDOT Autopilot is built to fix.

## The four-tier model

Every component in your codebase falls into one of four tiers. The tier determines the instrumentation approach.

### Tier A — Full Native EDOT Support (zero config)

Frameworks with official EDOT auto-instrumentation. Install the agent, set two environment variables, done. No code changes.

| Runtime | Frameworks |
|---|---|
| Java | Spring Boot, Quarkus, Micronaut, Servlet, JDBC, gRPC, Kafka, RabbitMQ |
| Python 3.7+ | Django, Flask, FastAPI, SQLAlchemy, Celery, Redis, psycopg2, aiohttp |
| Node.js | Express, Fastify, Koa, pg, mysql2, redis, amqplib, grpc-js |
| .NET 6+ | ASP.NET Core, Entity Framework Core, HttpClient, gRPC |
| PHP 8+ | Laravel, Symfony |

If your entire stack is Tier A, the EDOT SDK handles it. EDOT Autopilot still adds business-meaningful span attributes (Phase 3) and SLOs (Phase 4), but the basic wiring is automatic.

### Tier B — Partial Support (framework not covered, language is)

The language runtime is supported, but the specific framework is not covered by auto-instrumentation. You need to wrap entry points manually using the OTel SDK for that language.

Examples:
- **.NET Framework 4.x** (WebForms, WCF, MVC 5, Windows Services)
- **Python 2.7** if a compatible SDK version is available
- **Old Spring MVC** without Boot
- **Custom HTTP frameworks** in supported languages

Action: Manual span wrapping using the OTel SDK. See [.NET Framework 4.x guide](./opentelemetry-dotnet-framework-4x.md).

### Tier C — Language Supported, Library Not

The language has an OTel SDK, but a specific library your code uses does not have an OTel plugin. The library makes network calls, sends emails, charges payments, etc. — and none of it appears in traces.

Examples:
- Stripe, Twilio, SendGrid SDKs
- Proprietary SOAP clients
- Custom gRPC stubs
- Old ORMs with no OTel instrumentation

Action: Monkey-patch the library's public interface with spans. This is done once per library and requires no changes to calling code.

### Tier D — No OTel Support (Legacy Runtime / Unsupported Language)

No OTel SDK exists for this runtime. The language is not in scope for the OpenTelemetry specification. Manual SDK usage is impossible.

Examples:
- COBOL, RPG, PL/I, CICS
- Perl (no production-ready SDK)
- Classic ASP / VBScript
- PowerShell (no SDK)
- Bash / shell scripts
- Python 2.7 (no modern SDK)
- Fortran, MUMPS, Delphi, VB6
- Old PHP 5.x

Action: The **Telemetry Sidecar** pattern. Your legacy code makes HTTP POST calls; the sidecar translates them to OTLP and forwards to Elastic.

## Decision tree: which tier is my runtime?

```
Does an official EDOT agent/SDK exist for this language?
    |
    No ──────────────────────────────────────────────────> Tier D
    |                                                       Use Telemetry Sidecar
    Yes
    |
    Does the EDOT agent cover my specific framework/version?
        |
        Yes ──────────────────────────────────────────────> Tier A
        |                                                    Zero-config auto-instrumentation
        No
        |
        Does the OTel SDK for this language support my
        framework/version (even without auto-instrumentation)?
            |
            Yes ──────────────────────────────────────────> Tier B
            |                                                Manual span wrapping
            No (specific library not covered)
            |
            Can I wrap the library's public interface? ───> Tier C
                                                            Monkey-patching
```

### Quick reference table

| Technology | Tier | Approach |
|---|---|---|
| Java Spring Boot 2.x+ | A | EDOT auto-instrumentation |
| Python 3.7+ / Django / FastAPI | A | EDOT auto-instrumentation |
| Node.js / Express | A | EDOT auto-instrumentation |
| .NET 6+ / ASP.NET Core | A | EDOT auto-instrumentation |
| PHP 8+ / Laravel | A | EDOT auto-instrumentation |
| .NET Framework 4.6.2+ | B | Manual OTel SDK wrapping |
| Old Spring MVC (non-Boot) | B | Manual OTel SDK wrapping |
| Python 2.7 | D* | Sidecar (SDK approach fragile) |
| Stripe/Twilio in Python 3 | C | Monkey-patch |
| COBOL | D | Sidecar |
| Perl | D | Sidecar |
| Classic ASP / VBScript | D | Sidecar |
| PowerShell | D | Sidecar |
| Bash / shell scripts | D | Sidecar |
| Fortran | D | Sidecar |
| MUMPS / InterSystems Cache | D | Sidecar |
| RPG / AS400 | D | Sidecar |

*Python 2.7 technically has Tier B path with old SDK versions, but the sidecar is more reliable.

## The Telemetry Sidecar as a universal bridge

The Telemetry Sidecar is the core mechanism for Tier D runtimes. It works like this:

1. A Python 3 HTTP server (`otel-sidecar.py`) starts on `127.0.0.1:9411` on the same host as the legacy process.
2. The legacy code sends simple HTTP POST requests with a JSON body describing what happened.
3. The sidecar receives the request, creates an OTLP span, and forwards it to Elastic APM.
4. The call is fire-and-forget: the legacy code does not wait for a response, and if the sidecar is unreachable, the operation continues normally.

The sidecar supports seven actions:

| Action | Description |
|---|---|
| `event` | Emit a single point-in-time span |
| `start_span` | Begin a span, returns a span_id for duration tracking |
| `end_span` | End a started span, records duration and final attributes |

The key insight is that `curl`, `LWP::UserAgent`, `urllib2`, `MSXML2.ServerXMLHTTP`, and `Invoke-RestMethod` are available in virtually every runtime that has ever existed — even ones that were never designed for networked communication. As long as your legacy process can make an HTTP call, it can emit telemetry.

## Language-specific guides

- [COBOL](./opentelemetry-cobol.md) — mainframe transactions, batch jobs, payroll processing
- [Perl](./opentelemetry-perl.md) — CGI apps, bioinformatics pipelines, finance scripts
- [Bash / Shell Scripts](./opentelemetry-bash-shell-scripts.md) — backups, ETL, deployments, cron jobs
- [PowerShell](./opentelemetry-powershell.md) — Windows infrastructure, AD management, SQL Server ops
- [Classic ASP / VBScript](./opentelemetry-classic-asp-vbscript.md) — legacy IIS applications
- [.NET Framework 4.x](./opentelemetry-dotnet-framework-4x.md) — WebForms, WCF, MVC 5, Windows Services
- [Python 2.7](./opentelemetry-python2.md) — quant libraries, scientific computing, legacy Django

## What becomes visible in Elastic once instrumented

Before applying the sidecar pattern, a typical enterprise has a large "dark zone" — critical business processes that are completely invisible to APM. After instrumentation:

**Before:**
- Monitoring shows Kibana, Elasticsearch, and the Node.js API as healthy
- A business process fails → team finds out from a user report 90 minutes later
- Root cause: a COBOL batch job failed silently and did not feed data to the Node.js API
- Investigation: grep logs on a mainframe, call the DBA, page the person who knows the COBOL

**After:**
- Kibana APM shows `payroll-processor`, `supplier-reconciliation`, `invoice-generator` as named services
- A COBOL job failure → Elastic alert fires within 60 seconds
- Root cause visible immediately: `payroll.batch.complete` span is missing from today's run; the last successful span shows `records.processed: 0` with `error: "DB connection pool exhausted"`
- Investigation: click the span, see the full context, find the database issue

**The metric that matters**: mean time to understand (MTTU) — the time between an alert firing and the on-call engineer understanding what happened and what to do next. Business-enriched spans from legacy systems reduce this from hours to minutes.

## Related

- [Telemetry Sidecar Pattern — architecture and deployment](./telemetry-sidecar-pattern.md)
- [Business Span Enrichment — making spans actionable](./business-span-enrichment.md)
- [Elastic EDOT documentation](https://www.elastic.co/docs/reference/opentelemetry)
- [EDOT Autopilot on GitHub](https://github.com/gmoskovicz/edot-autopilot)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other legacy runtime developers find this solution.
