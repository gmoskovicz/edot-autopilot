#!/usr/bin/env python3
"""
Smoke test: Tier D — Tcl / network automation (sidecar simulation).

Simulates a Tcl Expect script submitting observability via the HTTP sidecar.
Business scenario: network device configuration management — SSH to routers,
push OSPF route changes, validate BGP peering, collect interface stats.

Run:
    cd smoke-tests && python3 42-tier-d-tcl/smoke.py
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
from opentelemetry.trace import SpanKind, StatusCode

SVC = "smoke-tier-d-tcl"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

devices_configured  = meter.create_counter("tcl.devices_configured")
ssh_sessions        = meter.create_counter("tcl.ssh_sessions")
config_push_ms      = meter.create_histogram("tcl.config_push_ms", unit="ms")
interface_errors    = meter.create_counter("tcl.interface_errors")

NETWORK_DEVICES = [
    {"hostname": "core-rtr-01.dc1",   "ip": "10.0.0.1",   "platform": "cisco_ios",    "role": "core",    "interfaces": 48},
    {"hostname": "edge-rtr-03.dc1",   "ip": "10.0.0.3",   "platform": "cisco_ios_xr", "role": "edge",    "interfaces": 24},
    {"hostname": "dist-sw-07.dc2",    "ip": "10.1.0.7",   "platform": "juniper_junos","role": "dist",    "interfaces": 96},
    {"hostname": "access-sw-22.dc2",  "ip": "10.1.1.22",  "platform": "cisco_nxos",   "role": "access",  "interfaces": 48},
]

ROUTE_CHANGES = [
    {"prefix": "192.168.100.0/24", "next_hop": "10.0.0.254", "action": "add"},
    {"prefix": "172.16.50.0/22",   "next_hop": "10.0.0.252", "action": "modify"},
    {"prefix": "10.50.0.0/16",     "next_hop": "null",        "action": "withdraw"},
]

def configure_device(device):
    t0 = time.time()
    error_count = 0

    with tracer.start_as_current_span("tcl.network_change_push", kind=SpanKind.INTERNAL,
            attributes={"tcl.script": "push_ospf_routes.tcl", "net.hostname": device["hostname"],
                        "net.ip": device["ip"], "net.platform": device["platform"],
                        "net.role": device["role"]}) as span:

        with tracer.start_as_current_span("tcl.expect.spawn_ssh", kind=SpanKind.CLIENT,
                attributes={"net.hostname": device["hostname"], "net.port": 22,
                            "net.protocol": "ssh"}):
            time.sleep(random.uniform(0.08, 0.25))
            ssh_sessions.add(1, attributes={"net.platform": device["platform"]})

        with tracer.start_as_current_span("tcl.expect.send_commands", kind=SpanKind.INTERNAL,
                attributes={"net.hostname": device["hostname"],
                            "net.command_count": len(ROUTE_CHANGES) * 2}):
            for route in ROUTE_CHANGES:
                time.sleep(random.uniform(0.02, 0.06))
                if random.random() < 0.05:
                    error_count += 1
                    interface_errors.add(1, attributes={"net.hostname": device["hostname"]})

        with tracer.start_as_current_span("tcl.expect.verify_bgp", kind=SpanKind.INTERNAL,
                attributes={"net.hostname": device["hostname"], "net.protocol": "bgp"}):
            time.sleep(random.uniform(0.05, 0.15))
            bgp_peers_up = random.randint(2, 8)
            logger.info("BGP peer state verified",
                        extra={"net.hostname": device["hostname"], "bgp.peers_up": bgp_peers_up})

        with tracer.start_as_current_span("tcl.expect.collect_interface_stats", kind=SpanKind.INTERNAL,
                attributes={"net.hostname": device["hostname"],
                            "net.interfaces_polled": device["interfaces"]}):
            time.sleep(random.uniform(0.1, 0.3))

        dur = (time.time() - t0) * 1000
        span.set_attribute("net.routes_pushed",    len(ROUTE_CHANGES))
        span.set_attribute("net.error_count",      error_count)
        span.set_attribute("tcl.push_duration_ms", round(dur, 2))

        if error_count > 0:
            span.set_status(StatusCode.ERROR, f"{error_count} command errors")

        devices_configured.add(1, attributes={"net.platform": device["platform"], "net.role": device["role"]})
        config_push_ms.record(dur, attributes={"net.platform": device["platform"]})

        logger.info("device configuration complete",
                    extra={"net.hostname": device["hostname"], "net.platform": device["platform"],
                           "net.routes_pushed": len(ROUTE_CHANGES), "net.error_count": error_count,
                           "tcl.push_duration_ms": round(dur, 2)})

    return error_count

print(f"\n[{SVC}] Simulating Tcl Expect network configuration push script...")
for device in NETWORK_DEVICES:
    errs = configure_device(device)
    icon = "⚠️ " if errs else "✅"
    print(f"  {icon} {device['hostname']:<28}  {device['platform']:<18}  routes={len(ROUTE_CHANGES)}  errors={errs}")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
