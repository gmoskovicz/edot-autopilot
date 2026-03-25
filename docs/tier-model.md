# The Four-Tier Coverage Model

This document explains why the four-tier model exists and how to apply it.

## The problem with binary "supported / unsupported"

Every existing observability tool makes a binary decision: either a framework is supported by their auto-instrumentation agent, or it isn't. If it isn't, the answer is "sorry, not supported."

This leaves enormous blind spots:
- The COBOL batch job that processes $50M in transactions every night
- The PowerShell script that provisions thousands of AD users weekly
- The SAP ABAP program that creates every purchase order in the company
- The Flutter app that half your customers use

These are not edge cases. They are the business.

## The four tiers

### Tier A — Full Native EDOT Support

The framework has first-class EDOT auto-instrumentation. Zero code changes needed.

| Language | Frameworks |
|----------|-----------|
| Python 3.8+ | Django, Flask, FastAPI, SQLAlchemy, Celery, Redis |
| Node.js | Express, Fastify, Koa, pg, mysql2, redis, amqplib |
| Java | Spring Boot, Quarkus, Micronaut, Servlet, JDBC, Kafka |
| .NET 6+ | ASP.NET Core, Entity Framework Core, HttpClient, gRPC |
| PHP 8+ | Laravel, Symfony |
| Ruby | Rails, Sinatra, Sidekiq |
| Go | net/http, gin, echo, gRPC |

**Action:** `edot-bootstrap` / `-javaagent` / `require()`. Done.

### Tier B — Language Supported, Framework Not

The OTel SDK exists for the language, but the specific framework or runtime version isn't auto-instrumented.

Examples:
- .NET Framework 4.x (EDOT requires .NET 6+)
- Python 2.7 (EDOT requires Python 3.8+)
- Old Spring MVC without auto-configuration
- Custom HTTP frameworks

**Action:** Manually create spans around entry points using the OTel SDK API.

The key insight: you only need to wrap **entry points** (HTTP handlers, queue consumers, scheduled jobs). Everything downstream of the entry point can use auto-instrumentation if available, or be instrumented selectively.

### Tier C — Language Supported, Library Not

The OTel SDK exists and is configured, but a specific third-party library has no OTel plugin.

Examples:
- Stripe SDK (no OTel plugin)
- Twilio SDK
- Legacy SOAP clients
- Custom gRPC stubs
- Old ORMs without OTel adapters

**Action:** Monkey-patch the library's public API at import time.

The key insight: `library.method = wrapped_version` is a one-time change that makes ALL calls to that library emitted as spans — with zero changes to the rest of the codebase.

### Tier D — No OTel SDK Exists

The runtime has no OpenTelemetry SDK and is unlikely to get one.

Examples:
- COBOL, RPG, PL/I, Natural
- Perl (OTel SDK is experimental/incomplete)
- Bash, PowerShell, CL scripts
- SAP ABAP
- Classic ASP / VBScript
- IBM AS/400 CL
- Flutter/Dart (no official EDOT distribution)

**Action:** Deploy the otel-sidecar on the same host. The legacy process makes HTTP POSTs; the sidecar translates to OTLP and forwards to Elastic.

The key insight: **any process that has existed since the mid-1990s can make an HTTP call.** curl shipped with most Unix systems since 1997. This covers everything.

## Decision tree

```
Does an EDOT SDK exist for this language/runtime?
├── Yes → Does EDOT auto-instrument this specific framework?
│         ├── Yes → Tier A (auto-instrumentation)
│         └── No  → Does the OTel SDK support this language version?
│                   ├── Yes → Tier B (manual wrapping) or Tier C (library patching)
│                   └── No  → Tier D (sidecar)
└── No  → Tier D (sidecar)
```

## Graceful degradation

The four tiers are not a hierarchy where Tier A is "good" and Tier D is "bad." They are a graceful degradation strategy. A Tier D COBOL program with three well-placed sidecar calls that report `order.id`, `order.value_usd`, and `fraud.decision` is infinitely more valuable than a Tier A FastAPI service with generic HTTP spans and no business context.

**Coverage is not the goal. Understanding is.**
