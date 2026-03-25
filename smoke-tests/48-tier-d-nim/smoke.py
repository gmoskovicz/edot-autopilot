#!/usr/bin/env python3
"""
Smoke test: Tier D — Nim high-performance systems (sidecar simulation).

Simulates a Nim binary submitting observability via the HTTP sidecar.
Business scenario: high-throughput message parser for financial market data —
parse FIX 4.4 protocol messages, normalize to internal format, route to handlers.

Run:
    cd smoke-tests && python3 48-tier-d-nim/smoke.py
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

SVC = "smoke-tier-d-nim"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

messages_parsed   = meter.create_counter("nim.messages_parsed")
parse_errors      = meter.create_counter("nim.parse_errors")
message_latency   = meter.create_histogram("nim.parse_latency_us", unit="us")
order_volume      = meter.create_histogram("nim.order_notional_usd", unit="USD")

FIX_MESSAGES = [
    {"msg_type": "D", "cl_ord_id": f"ORD-{uuid.uuid4().hex[:8]}", "symbol": "AAPL",  "side": "1", "qty": 1000,  "price": 217.45, "ord_type": "2"},  # New Order Single
    {"msg_type": "D", "cl_ord_id": f"ORD-{uuid.uuid4().hex[:8]}", "symbol": "MSFT",  "side": "2", "qty": 500,   "price": 415.20, "ord_type": "2"},
    {"msg_type": "G", "cl_ord_id": f"ORD-{uuid.uuid4().hex[:8]}", "symbol": "NVDA",  "side": "1", "qty": 200,   "price": 875.00, "ord_type": "2"},  # Order Cancel/Replace
    {"msg_type": "F", "cl_ord_id": f"ORD-{uuid.uuid4().hex[:8]}", "symbol": "GOOGL", "side": "1", "qty": 100,   "price": 0,      "ord_type": "1"},  # Order Cancel
    {"msg_type": "D", "cl_ord_id": f"ORD-{uuid.uuid4().hex[:8]}", "symbol": "TSLA",  "side": "2", "qty": 750,   "price": 289.30, "ord_type": "2"},
    {"msg_type": "8", "cl_ord_id": f"ORD-{uuid.uuid4().hex[:8]}", "symbol": "AMZN",  "side": "1", "qty": 300,   "price": 228.90, "ord_type": "2"},  # Execution Report
]

MSG_TYPE_NAMES = {"D": "NewOrderSingle", "G": "OrderCancelReplaceRequest",
                  "F": "OrderCancelRequest", "8": "ExecutionReport"}

def parse_fix_message(msg):
    t0 = time.perf_counter()
    is_error = random.random() < 0.03
    notional = msg["qty"] * msg["price"] if msg["price"] > 0 else 0

    with tracer.start_as_current_span("nim.fix_parser.parse", kind=SpanKind.INTERNAL,
            attributes={"nim.proc": "parseFIXMessage", "fix.msg_type": msg["msg_type"],
                        "fix.msg_type_name": MSG_TYPE_NAMES.get(msg["msg_type"], "Unknown"),
                        "fix.symbol": msg["symbol"], "fix.side": msg["side"],
                        "fix.qty": msg["qty"]}) as span:
        time.sleep(random.uniform(0.0001, 0.0004))  # sub-millisecond

        if is_error:
            span.set_status(StatusCode.ERROR, "malformed field 38")
            parse_errors.add(1, attributes={"fix.msg_type": msg["msg_type"]})
            logger.warning("FIX parse error",
                           extra={"fix.cl_ord_id": msg["cl_ord_id"], "fix.symbol": msg["symbol"],
                                  "fix.error": "malformed_qty_field"})
            return None

        with tracer.start_as_current_span("nim.fix_parser.route", kind=SpanKind.INTERNAL,
                attributes={"nim.proc": "routeToHandler", "fix.msg_type": msg["msg_type"]}):
            time.sleep(random.uniform(0.00002, 0.00008))

        lat_us = (time.perf_counter() - t0) * 1_000_000
        span.set_attribute("fix.cl_ord_id",    msg["cl_ord_id"])
        span.set_attribute("fix.notional_usd", round(notional, 2))
        span.set_attribute("fix.latency_us",   round(lat_us, 3))

        messages_parsed.add(1, attributes={"fix.msg_type": msg["msg_type"],
                                            "fix.symbol":   msg["symbol"]})
        message_latency.record(lat_us, attributes={"fix.msg_type": msg["msg_type"]})
        if notional > 0:
            order_volume.record(notional, attributes={"fix.symbol": msg["symbol"]})

        logger.info("FIX message parsed",
                    extra={"fix.cl_ord_id": msg["cl_ord_id"], "fix.symbol": msg["symbol"],
                           "fix.msg_type_name": MSG_TYPE_NAMES.get(msg["msg_type"]),
                           "fix.qty": msg["qty"], "fix.notional_usd": round(notional, 2),
                           "fix.latency_us": round(lat_us, 3)})
    return lat_us

print(f"\n[{SVC}] Simulating Nim FIX protocol message parser...")
for msg in FIX_MESSAGES:
    lat = parse_fix_message(msg)
    notional = msg["qty"] * msg["price"]
    type_name = MSG_TYPE_NAMES.get(msg["msg_type"], "Unknown")
    if lat:
        print(f"  ✅ {type_name:<30}  {msg['symbol']:<6}  qty={msg['qty']:>5}  notional=${notional:>12,.2f}  lat={lat:.1f}μs")
    else:
        print(f"  ❌ {type_name:<30}  {msg['symbol']:<6}  PARSE ERROR")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
