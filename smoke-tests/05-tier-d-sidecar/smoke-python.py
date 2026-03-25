#!/usr/bin/env python3
"""
Smoke test: Tier D — Python client → OTEL Sidecar (traces + logs + metrics)

Tests the sidecar HTTP API using the same pattern that COBOL, Bash, Perl,
PowerShell, and SAP ABAP would use. No OTel SDK — plain HTTP only.

Run:
    cd smoke-tests && python3 05-tier-d-sidecar/smoke-python.py
"""

import os, json, urllib.request, uuid, time
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

SIDECAR = os.environ.get("OTEL_SIDECAR_URL", "http://127.0.0.1:9411")
SVC     = "smoke-tier-d-sidecar-client"


def post(payload: dict) -> dict:
    """Plain HTTP POST — exactly what any legacy language does."""
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(SIDECAR, data, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [warn] sidecar unreachable: {e}")
        return {}


def otel_event(name, **attrs):
    return post({"action": "event", "name": name, "attributes": attrs})

def otel_start(name, traceparent=None, **attrs):
    payload = {"action": "start_span", "name": name, "attributes": attrs}
    if traceparent:
        payload["traceparent"] = traceparent
    r = post(payload)
    return r.get("span_id", ""), r.get("traceparent", "")

def otel_end(span_id, error=None, **attrs):
    if not span_id: return
    payload = {"action": "end_span", "span_id": span_id, "attributes": attrs}
    if error: payload["error"] = error
    post(payload)

def otel_log(severity, message, traceparent=None, **attrs):
    payload = {"action": "log", "severity": severity, "body": message, "attributes": attrs}
    if traceparent:
        payload["traceparent"] = traceparent
    post(payload)

def otel_counter(name, value=1, **attrs):
    post({"action": "metric_counter", "name": name, "value": value, "attributes": attrs})

def otel_histogram(name, value, **attrs):
    post({"action": "metric_histogram", "name": name, "value": value, "attributes": attrs})


print(f"\n[{SVC}] Testing sidecar at {SIDECAR} ...")

# Health check
health = post({"action": "health"})
if not health.get("ok"):
    print("  ❌ Sidecar not responding. Start it first: see 05-tier-d-sidecar/start-sidecar.sh")
    raise SystemExit(1)
print(f"  ✅ Sidecar healthy  active_spans={health.get('spans_active', 0)}")

# ── Test 1: fire-and-forget events (COBOL/Batch pattern) ─────────────────────
print("\n  Test 1: fire-and-forget events (COBOL/Batch pattern)")
for order_id, amount, tier in [
    (f"COBOL-{uuid.uuid4().hex[:6].upper()}", 4200.0, "enterprise"),
    (f"COBOL-{uuid.uuid4().hex[:6].upper()}", 29.99,  "free"),
]:
    otel_event("order.processed",
               **{"order.id": order_id, "order.value_usd": amount,
                  "customer.tier": tier, "language": "cobol"})
    otel_log("INFO", f"COBOL order processed: {order_id}",
             **{"order.id": order_id, "order.value_usd": amount, "customer.tier": tier})
    otel_counter("cobol.orders.processed", 1, **{"customer.tier": tier})
    print(f"  ✅ event: order.processed  {order_id}  ${amount:.2f}  [{tier}]")

# ── Test 2: multi-step spans with logs + metrics (ETL pattern) ────────────────
print("\n  Test 2: multi-step ETL spans (Perl/PowerShell pattern)")
t0 = time.time()
batch_id, batch_tp = otel_start("etl.batch",
                                **{"batch.source": "legacy-erp", "batch.rows_expected": 50000})
otel_log("INFO", "ETL batch started", batch_tp,
         **{"batch.source": "legacy-erp", "batch.rows_expected": 50000})
otel_counter("etl.batches.started", 1, **{"batch.source": "legacy-erp"})

time.sleep(0.1)
otel_event("etl.extract.done", **{"extract.rows": 49832, "extract.source": "oracle",
                                   "extract.duration_ms": 820})
otel_log("INFO", "Extract complete: 49832 rows", batch_tp,
         **{"extract.rows": 49832, "extract.source": "oracle"})
otel_counter("etl.rows.extracted", 49832, **{"source": "oracle"})

time.sleep(0.05)
duration_ms = int((time.time() - t0) * 1000)
otel_end(batch_id, **{"batch.rows_processed": 49832, "batch.status": "success",
                      "batch.duration_ms": duration_ms})
otel_histogram("etl.batch.duration_ms", duration_ms,
               **{"batch.source": "legacy-erp", "batch.status": "success"})
otel_log("INFO", "ETL batch completed", batch_tp,
         **{"batch.rows_processed": 49832, "batch.duration_ms": duration_ms})
print(f"  ✅ multi-step span: etl.batch  rows=49832  duration={duration_ms}ms")

# ── Test 3: error span with error log (payment failure pattern) ───────────────
print("\n  Test 3: error span + error log")
err_id, err_tp = otel_start("payment.process",
                            **{"payment.amount_usd": 9999.0, "payment.provider": "stripe",
                               "payment.currency": "usd"})
otel_log("INFO", "Payment attempt started", err_tp,
         **{"payment.amount_usd": 9999.0, "payment.provider": "stripe"})
time.sleep(0.05)
otel_end(err_id, error="Card declined: insufficient funds",
         **{"payment.error_code": "card_declined", "payment.attempt": 1,
            "payment.amount_usd": 9999.0})
otel_log("ERROR", "Payment failed: Card declined: insufficient funds", err_tp,
         **{"payment.error_code": "card_declined", "payment.attempt": 1,
            "payment.amount_usd": 9999.0})
otel_counter("payment.failures", 1, **{"error_code": "card_declined", "provider": "stripe"})
print(f"  ✅ error span + log: payment.process  error=card_declined")

print(f"\n[{SVC}] Done → Kibana APM → {SVC}")
