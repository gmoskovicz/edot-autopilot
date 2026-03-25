#!/usr/bin/env python3
"""
Smoke test: Tier D — AWK ETL pipeline (sidecar simulation).

Simulates an AWK + shell ETL pipeline submitting observability via the HTTP
sidecar. Business scenario: access log analytics — parse Apache/Nginx access
logs, aggregate by endpoint and status, compute p99 latency, write summary CSV.

Run:
    cd smoke-tests && python3 43-tier-d-awk-etl/smoke.py
"""

import os, sys, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-d-awk-etl"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

lines_processed   = meter.create_counter("awk.lines_processed")
files_processed   = meter.create_counter("awk.files_processed")
etl_duration      = meter.create_histogram("awk.etl_duration_ms", unit="ms")
error_lines       = meter.create_counter("awk.parse_errors")

LOG_FILES = [
    {"path": "/var/log/nginx/access_2026-02-28.log", "lines": 142_831, "server": "web-01"},
    {"path": "/var/log/nginx/access_2026-02-28.log", "lines": 98_445,  "server": "web-02"},
    {"path": "/var/log/apache2/access_2026-02-28.log","lines": 55_120,  "server": "api-01"},
]

ENDPOINTS = [
    ("/api/v1/products",   200, 45),
    ("/api/v1/orders",     200, 120),
    ("/api/v1/auth/token", 200, 18),
    ("/api/v1/cart",       200, 35),
    ("/api/v1/products",   404, 12),
    ("/health",            200, 5),
    ("/api/v1/checkout",   500, 8),
]

def process_log_file(log_file):
    t0 = time.time()
    parse_errors = int(log_file["lines"] * random.uniform(0.0001, 0.002))

    with tracer.start_as_current_span("awk.etl_pipeline", kind=SpanKind.INTERNAL,
            attributes={"awk.script": "parse_access_logs.awk", "etl.input_file": log_file["path"],
                        "etl.server": log_file["server"], "etl.expected_lines": log_file["lines"]}) as span:

        with tracer.start_as_current_span("awk.parse_log", kind=SpanKind.INTERNAL,
                attributes={"awk.command": "awk -F'\"' '{print $1,$2,$3}'",
                            "etl.input_file": log_file["path"]}):
            time.sleep(random.uniform(0.05, 0.20))
            lines_processed.add(log_file["lines"], attributes={"etl.server": log_file["server"]})
            if parse_errors:
                error_lines.add(parse_errors, attributes={"etl.server": log_file["server"]})

        endpoint_stats = {}
        with tracer.start_as_current_span("awk.aggregate_by_endpoint", kind=SpanKind.INTERNAL,
                attributes={"awk.command": "awk '{count[$7]++; sum[$7]+=$NF} END {for(k in count) print k,count[k],sum[k]/count[k]}'"}):
            time.sleep(random.uniform(0.03, 0.10))
            for ep, status, base_ms in ENDPOINTS:
                hits = int(log_file["lines"] * random.uniform(0.01, 0.15))
                p99  = base_ms * random.uniform(1.5, 8.0)
                endpoint_stats[ep] = {"hits": hits, "status": status, "p99_ms": round(p99, 1)}

        with tracer.start_as_current_span("awk.write_summary_csv", kind=SpanKind.INTERNAL,
                attributes={"etl.output_file": f"reports/{log_file['server']}_summary.csv",
                            "etl.rows_written": len(endpoint_stats)}):
            time.sleep(random.uniform(0.005, 0.015))

        dur = (time.time() - t0) * 1000
        span.set_attribute("etl.lines_processed", log_file["lines"])
        span.set_attribute("etl.parse_errors",    parse_errors)
        span.set_attribute("etl.endpoints_found", len(endpoint_stats))
        span.set_attribute("awk.duration_ms",     round(dur, 2))

        files_processed.add(1, attributes={"etl.server": log_file["server"]})
        etl_duration.record(dur, attributes={"etl.server": log_file["server"]})

        logger.info("log file ETL complete",
                    extra={"etl.server": log_file["server"], "etl.lines_processed": log_file["lines"],
                           "etl.parse_errors": parse_errors, "etl.endpoints_found": len(endpoint_stats),
                           "awk.duration_ms": round(dur, 2)})

    return log_file["lines"], parse_errors

print(f"\n[{SVC}] Simulating AWK access log ETL pipeline...")
for log_file in LOG_FILES:
    lines, errs = process_log_file(log_file)
    print(f"  ✅ {log_file['server']:<12}  lines={lines:>8,}  parse_errors={errs:>4}  file={Path(log_file['path']).name}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
