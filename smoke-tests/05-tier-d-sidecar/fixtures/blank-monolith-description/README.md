# Legacy Monolith — Multi-Language System

This is a description of a multi-language legacy system that cannot be instrumented
with native OTel SDKs. Run `Observe this project.` to add sidecar-based observability.

## Services & Languages

| Service              | Language      | Why Tier D                         |
|----------------------|---------------|------------------------------------|
| payroll-processor    | COBOL         | Mainframe z/OS, no OTel SDK        |
| batch-etl            | Bash + AWK    | Shell scripts, fire-and-forget      |
| report-engine        | Perl 5.8      | Legacy, no OTLP client available   |
| config-manager       | PowerShell    | Windows-only admin scripts         |

## Current Architecture

```
Batch Scheduler (cron)
  └── payroll-processor.cbl   — COBOL batch job, runs nightly
  └── batch-etl.sh            — Bash ETL pipeline, reads Oracle, writes S3
  └── report-engine.pl        — Perl report generator, emails CFO
  └── config-manager.ps1      — PowerShell AD provisioning
```

## No Observability

None of these runtimes support native OpenTelemetry SDKs. They need an HTTP
sidecar that accepts simple JSON payloads and forwards to OTLP.
