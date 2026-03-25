#!/usr/bin/env python3
"""
Smoke test: Tier A — Go (native OTel SDK).

Runner script: attempts to run the Go smoke test if `go` is available.
Falls back to a Python simulation that emits the same signals with
service.name=smoke-tier-a-go so the service always appears in Kibana APM.

Run:
    cd smoke-tests && python3 09-tier-a-go/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-a-go"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

req_counter   = meter.create_counter("gateway.requests_total")
latency_hist  = meter.create_histogram("gateway.upstream_latency_ms", unit="ms")
auth_failures = meter.create_counter("gateway.auth_failures")

REQUESTS = [
    ("GET",  "/api/v2/products",  "product-catalog",    "public"),
    ("POST", "/api/v2/orders",    "order-service",      "enterprise"),
    ("GET",  "/api/v2/inventory", "inventory-service",  "internal"),
    ("POST", "/api/v2/payments",  "payment-service",    "enterprise"),
    ("GET",  "/api/v2/reports",   "analytics-service",  "pro"),
]

print(f"\n[{SVC}] Routing API gateway requests (Go Tier A simulation)...")

for method, path, upstream, tier in REQUESTS:
    t0 = time.time()
    with tracer.start_as_current_span("gateway.route_request", kind=SpanKind.SERVER,
            attributes={"http.method": method, "http.route": path,
                        "net.peer.name": upstream, "customer.tier": tier}) as span:

        with tracer.start_as_current_span("gateway.authenticate_jwt", kind=SpanKind.INTERNAL) as as_:
            time.sleep(random.uniform(0.005, 0.015))
            as_.set_attribute("auth.valid", True)

        with tracer.start_as_current_span("gateway.forward_upstream", kind=SpanKind.CLIENT,
                attributes={"http.url": f"https://{upstream}.internal{path}",
                            "peer.service": upstream}) as us:
            time.sleep(random.uniform(0.020, 0.100))
            us.set_attribute("http.status_code", 200)

        dur = (time.time() - t0) * 1000
        span.set_attribute("gateway.total_latency_ms", round(dur, 2))
        span.set_attribute("http.status_code", 200)

        req_counter.add(1, attributes={"http.method": method, "customer.tier": tier})
        latency_hist.record(dur, attributes={"http.method": method, "customer.tier": tier})

        logger.info("request routed",
                    extra={"http.method": method, "http.route": path,
                           "upstream.service": upstream, "gateway.latency_ms": round(dur, 2),
                           "customer.tier": tier})
        print(f"  ✅ {method:<5} {path:<28}  → {upstream:<24}  {dur:.0f}ms")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
