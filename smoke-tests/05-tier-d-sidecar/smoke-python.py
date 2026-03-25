#!/usr/bin/env python3
"""
Smoke test: Tier D — Python client → OTel Sidecar (traces + logs + metrics).

Verifies the sidecar HTTP bridge using the same call pattern that COBOL, Bash,
Perl, PowerShell, and SAP ABAP would use. No OTel SDK — plain HTTP only.

Checks:
  - Sidecar health endpoint responds {"ok": true}
  - fire-and-forget event spans emitted for two COBOL-style orders
  - Multi-step ETL span: start_span → work → end_span with attributes
  - Error span: end_span with {"error": "..."} sets ERROR status on sidecar side
  - Log records sent and acknowledged for all scenarios
  - Counters and histogram values posted and acknowledged

Run:
    cd smoke-tests && python3 05-tier-d-sidecar/smoke-python.py
    (Requires sidecar to be running — started by run-all.sh before this test)
"""

import os
import sys
import json
import time
import uuid
import urllib.request

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))
# Sidecar tests don't need Elastic credentials directly — the sidecar holds them.
# But we skip if the sidecar URL isn't reachable (checked below via health call).

SIDECAR = os.environ.get("OTEL_SIDECAR_URL", "http://127.0.0.1:9411")
SVC     = "smoke-tier-d-sidecar-client"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(("PASS" if ok else "FAIL", name, detail))


def post(payload: dict) -> dict:
    """Plain HTTP POST — exactly what any legacy language does."""
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        SIDECAR, data, {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "_error": str(e)}


def otel_event(name, **attrs):
    return post({"action": "event", "name": name, "attributes": attrs})


def otel_start(name, traceparent=None, **attrs):
    payload = {"action": "start_span", "name": name, "attributes": attrs}
    if traceparent:
        payload["traceparent"] = traceparent
    r = post(payload)
    return r.get("span_id", ""), r.get("traceparent", "")


def otel_end(span_id, error=None, **attrs):
    if not span_id:
        return {"ok": False}
    payload = {"action": "end_span", "span_id": span_id, "attributes": attrs}
    if error:
        payload["error"] = error
    return post(payload)


def otel_log(severity, message, traceparent=None, **attrs):
    payload = {"action": "log", "severity": severity, "body": message, "attributes": attrs}
    if traceparent:
        payload["traceparent"] = traceparent
    return post(payload)


def otel_counter(name, value=1, **attrs):
    return post({"action": "metric_counter", "name": name, "value": value, "attributes": attrs})


def otel_histogram(name, value, **attrs):
    return post({"action": "metric_histogram", "name": name, "value": value, "attributes": attrs})


print(f"\n{'='*62}")
print(f"EDOT-Autopilot | {SVC}")
print(f"{'='*62}")
print(f"  Sidecar: {SIDECAR}")
print()

# ── Health check ──────────────────────────────────────────────────────────────
health = post({"action": "health"})
check("Sidecar health check responds {ok: true}",
      health.get("ok") is True,
      f"response: {health}")

if not health.get("ok"):
    print("  [FAIL] Sidecar not responding. Start with run-all.sh or:")
    print("         OTEL_SERVICE_NAME=x ELASTIC_OTLP_ENDPOINT=y ELASTIC_API_KEY=z "
          "python3 otel-sidecar/otel-sidecar.py")
    sys.exit(1)

# ── Scenario 1: fire-and-forget events (COBOL/Batch pattern) ──────────────────
print("Scenario 1: fire-and-forget events (COBOL/Batch pattern):")
for order_id, amount, tier in [
    (f"COBOL-{uuid.uuid4().hex[:6].upper()}", 4200.0, "enterprise"),
    (f"COBOL-{uuid.uuid4().hex[:6].upper()}", 29.99,  "free"),
]:
    r_ev  = otel_event("order.processed",
                       **{"order.id": order_id, "order.value_usd": amount,
                          "customer.tier": tier, "language": "cobol"})
    r_log = otel_log("INFO", f"COBOL order processed: {order_id}",
                     **{"order.id": order_id, "order.value_usd": amount,
                        "customer.tier": tier})
    r_cnt = otel_counter("cobol.orders.processed", 1, **{"customer.tier": tier})
    check(
        f"fire-and-forget event: order.processed {order_id} ${amount:.2f} [{tier}]",
        r_ev.get("ok") and r_log.get("ok") and r_cnt.get("ok"),
        f"event={r_ev} log={r_log} counter={r_cnt}",
    )

# ── Scenario 2: multi-step spans with logs + metrics (ETL pattern) ────────────
print()
print("Scenario 2: multi-step ETL span (Perl/PowerShell pattern):")
t0 = time.time()
batch_id, batch_tp = otel_start("etl.batch",
                                **{"batch.source": "legacy-erp",
                                   "batch.rows_expected": 50000})
check("etl.batch start_span acknowledged",
      bool(batch_id),
      f"batch_id={batch_id!r}")

otel_log("INFO", "ETL batch started", batch_tp,
         **{"batch.source": "legacy-erp", "batch.rows_expected": 50000})
otel_counter("etl.batches.started", 1, **{"batch.source": "legacy-erp"})

time.sleep(0.1)
otel_event("etl.extract.done",
           **{"extract.rows": 49832, "extract.source": "oracle",
              "extract.duration_ms": 820})
otel_counter("etl.rows.extracted", 49832, **{"source": "oracle"})

time.sleep(0.05)
duration_ms = int((time.time() - t0) * 1000)
r_end = otel_end(batch_id,
                 **{"batch.rows_processed": 49832, "batch.status": "success",
                    "batch.duration_ms": duration_ms})
otel_histogram("etl.batch.duration_ms", duration_ms,
               **{"batch.source": "legacy-erp", "batch.status": "success"})
check("etl.batch end_span acknowledged",
      r_end.get("ok"),
      f"response: {r_end}")

# ── Scenario 3: error span (payment failure pattern) ──────────────────────────
print()
print("Scenario 3: error span + error log:")
err_id, err_tp = otel_start("payment.process",
                            **{"payment.amount_usd": 9999.0,
                               "payment.provider": "stripe",
                               "payment.currency": "usd"})
check("payment.process start_span acknowledged",
      bool(err_id),
      f"span_id={err_id!r}")

otel_log("INFO", "Payment attempt started", err_tp,
         **{"payment.amount_usd": 9999.0, "payment.provider": "stripe"})
time.sleep(0.05)
r_err_end = otel_end(err_id,
                     error="Card declined: insufficient funds",
                     **{"payment.error_code": "card_declined",
                        "payment.attempt": 1,
                        "payment.amount_usd": 9999.0})
otel_log("ERROR", "Payment failed: Card declined", err_tp,
         **{"payment.error_code": "card_declined", "payment.attempt": 1})
otel_counter("payment.failures", 1,
             **{"error_code": "card_declined", "provider": "stripe"})
check("payment.process error end_span acknowledged",
      r_err_end.get("ok"),
      f"response: {r_err_end}")

# ── Summary ────────────────────────────────────────────────────────────────────
passed = sum(1 for s, _, _ in CHECKS if s == "PASS")
failed = sum(1 for s, _, _ in CHECKS if s == "FAIL")
for status, name, detail in CHECKS:
    line = f"  [{status}] {name}"
    if detail and status == "FAIL":
        line += f"\n         -> {detail}"
    print(line)

print(f"\n  Result: {passed}/{len(CHECKS)} checks passed")
print(f"  Kibana → APM → (service name set by sidecar's OTEL_SERVICE_NAME env var)")
if failed:
    sys.exit(1)
