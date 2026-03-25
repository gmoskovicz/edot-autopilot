#!/usr/bin/env python3
"""
Smoke test: Tier D — Python client → OTEL Sidecar

Tests the sidecar HTTP API directly using the same pattern that
COBOL, Bash, Perl, PowerShell, and SAP ABAP would use.
Sends spans as a plain HTTP client — no OTel SDK involved.

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

def otel_start(name, **attrs):
    r = post({"action": "start_span", "name": name, "attributes": attrs})
    return r.get("span_id", "")

def otel_end(span_id, error=None, **attrs):
    if not span_id: return
    payload = {"action": "end_span", "span_id": span_id, "attributes": attrs}
    if error: payload["error"] = error
    post(payload)


print(f"\n[{SVC}] Testing sidecar at {SIDECAR} ...")

# Health check
health = post({"action": "health"})
if not health.get("ok"):
    print("  ❌ Sidecar not responding. Start it first: see 05-tier-d-sidecar/start-sidecar.sh")
    raise SystemExit(1)
print(f"  ✅ Sidecar healthy  active_spans={health.get('spans_active', 0)}")

# Test 1: fire-and-forget events (COBOL/Bash pattern)
print("\n  Test 1: fire-and-forget events (COBOL/Bash pattern)")
for i, (order_id, amount, tier) in enumerate([
    (f"COBOL-{uuid.uuid4().hex[:6].upper()}", 4200.0, "enterprise"),
    (f"COBOL-{uuid.uuid4().hex[:6].upper()}", 29.99,  "free"),
]):
    otel_event("order.processed",
               **{"order.id": order_id, "order.value_usd": amount,
                  "customer.tier": tier, "language": "cobol"})
    print(f"  ✅ event: order.processed  {order_id}  ${amount:.2f}  [{tier}]")

# Test 2: multi-step spans (Perl/PowerShell pattern)
print("\n  Test 2: multi-step spans (Perl/PowerShell pattern)")
batch_id = otel_start("etl.batch",
                      **{"batch.source": "legacy-erp", "batch.rows_expected": 50000})
time.sleep(0.1)
otel_event("etl.extract.done", **{"extract.rows": 49832, "extract.source": "oracle"})
time.sleep(0.05)
otel_end(batch_id, **{"batch.rows_processed": 49832, "batch.status": "success"})
print(f"  ✅ multi-step span: etl.batch  rows=49832")

# Test 3: error span
print("\n  Test 3: error span")
err_id = otel_start("payment.process",
                    **{"payment.amount": 9999.0, "payment.provider": "stripe"})
time.sleep(0.05)
otel_end(err_id, error="Card declined: insufficient funds",
         **{"payment.error_code": "card_declined", "payment.attempt": 1})
print(f"  ✅ error span: payment.process  error=card_declined")

print(f"\n[{SVC}] Done → Kibana APM → {SVC}")
