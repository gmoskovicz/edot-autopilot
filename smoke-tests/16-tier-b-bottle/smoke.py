#!/usr/bin/env python3
"""
Smoke test: Tier B — Bottle micro-framework (no EDOT instrumentation).

Wraps Bottle route functions manually.
Business scenario: Internal server decommission API — check dependencies,
drain load balancer, archive the server record.

Run:
    cd smoke-tests && python3 16-tier-b-bottle/smoke.py
"""

import os, sys, uuid, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-b-bottle"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

decom_counter = meter.create_counter("infra.decommissions")
drain_latency = meter.create_histogram("infra.lb_drain_ms", unit="ms")


# ── Tier B: Bottle route decorator wrapper ────────────────────────────────────
def bottle_route(path, method="GET"):
    """Replaces @route() from Bottle with an OTel-instrumented equivalent."""
    def decorator(fn):
        def wrapped(*args, **kwargs):
            with tracer.start_as_current_span(
                f"{method} {path}", kind=SpanKind.SERVER,
                attributes={"http.method": method, "http.route": path, "framework": "bottle"},
            ) as span:
                try:
                    result = fn(*args, **kwargs)
                    span.set_attribute("http.status_code", result.get("status", 200))
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR, str(e))
                    raise
        return wrapped
    return decorator


# ── Application routes — ZERO CHANGES except the decorator ───────────────────
@bottle_route("/api/infra/servers/<hostname>/decommission", "POST")
def decommission_server(hostname, payload=None):
    datacenter = payload.get("datacenter", "dc-unknown")
    reason     = payload.get("reason", "end-of-life")

    # Step 1: check dependencies
    with tracer.start_as_current_span("infra.dependency_check", kind=SpanKind.CLIENT,
        attributes={"server.hostname": hostname, "server.datacenter": datacenter}) as dep_span:
        time.sleep(0.02)
        dep_count = random.randint(0, 3)
        dep_span.set_attribute("server.active_dependencies", dep_count)

    if dep_count > 0:
        logger.warning("decommission blocked: active dependencies found",
                       extra={"server.hostname": hostname, "dependencies.count": dep_count})

    # Step 2: drain load balancer
    t0 = time.time()
    with tracer.start_as_current_span("infra.lb_drain", kind=SpanKind.CLIENT,
        attributes={"server.hostname": hostname, "lb.action": "drain"}) as lb_span:
        time.sleep(0.04)
        connections = random.randint(0, 50)
        lb_span.set_attribute("lb.connections_drained", connections)
        lb_span.set_attribute("lb.drain_status", "complete")
        drain_latency.record((time.time() - t0) * 1000, attributes={"datacenter": datacenter})

    # Step 3: archive
    archive_id = f"ARCH-{uuid.uuid4().hex[:8].upper()}"
    logger.info("server decommissioned",
                extra={"server.hostname": hostname, "server.datacenter": datacenter,
                       "decommission.reason": reason, "decommission.archive_id": archive_id,
                       "lb.connections_drained": connections})

    decom_counter.add(1, attributes={"datacenter": datacenter, "reason": reason})
    return {"status": 200, "archive_id": archive_id, "hostname": hostname}


servers = [
    {"hostname": "web-prod-07", "datacenter": "us-east-1",  "reason": "end-of-life"},
    {"hostname": "db-replica-3","datacenter": "eu-west-1",  "reason": "replaced"},
    {"hostname": "cache-02",    "datacenter": "us-east-1",  "reason": "hardware-failure"},
]

print(f"\n[{SVC}] Simulating Bottle infra API (manual route wrapping)...")
for server in servers:
    result = decommission_server(server["hostname"], payload=server)
    print(f"  ✅ {server['hostname']:<20}  {server['datacenter']}  "
          f"archive={result['archive_id']}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
