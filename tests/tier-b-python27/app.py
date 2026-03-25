"""
Tier B — Python 2.7 with manual OTel wrapping.

Python 2.7 reached end-of-life in January 2020 but still runs in
enterprise environments (legacy Django 1.x apps, old CGI scripts).
EDOT's Python SDK requires Python 3.8+. For Python 2.7, the OTel SDK
is not available — but we can still instrument if Python 3 is also
available on the same host (e.g. via the sidecar approach).

This file shows TWO approaches:
  1. If Python 3 + OTel is available alongside: manual SDK wrapping
  2. If only Python 2.7: use the sidecar (Tier D approach)

NOTE: This file is written for Python 3 to be runnable, but the
patterns shown represent how you'd instrument a Python 2.7 codebase
by either upgrading to OTel SDK manually or using the sidecar.
"""

from __future__ import print_function
import os
import json
import random

try:
    # Approach 1: OTel SDK available (Python 3 or backported)
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.trace import SpanKind

    endpoint = os.environ.get("ELASTIC_OTLP_ENDPOINT", "").rstrip("/")
    api_key  = os.environ.get("ELASTIC_API_KEY", "")
    svc_name = os.environ.get("OTEL_SERVICE_NAME", "python27-tier-b")

    resource = Resource.create({
        "service.name":           svc_name,
        "deployment.environment": os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "development"),
    })
    exporter = OTLPSpanExporter(
        endpoint="{}/v1/traces".format(endpoint),
        headers={"Authorization": "ApiKey {}".format(api_key)},
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("python27-manual")

    USE_OTEL_SDK = True
    print("[python27-tier-b] Using OTel SDK (Approach 1)")

except ImportError:
    USE_OTEL_SDK = False
    print("[python27-tier-b] OTel SDK not available, using sidecar (Approach 2)")

    # ── Approach 2: Sidecar fallback ─────────────────────────────────────────
    try:
        import urllib2 as urlreq   # Python 2
    except ImportError:
        import urllib.request as urlreq  # Python 3 fallback

    SIDECAR = os.environ.get("OTEL_SIDECAR_URL", "http://127.0.0.1:9411")

    def _sidecar_post(payload):
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urlreq.Request(SIDECAR, data, {"Content-Type": "application/json"})
            urlreq.urlopen(req, timeout=1)
        except Exception:
            pass  # never block business logic


# ── Tier B pattern: instrument_handler wrapper ────────────────────────────────
def instrument_handler(handler_fn, route, method="GET"):
    """
    Wraps a handler function with an OTel span.
    This is the Tier B pattern — apply to every entry point.
    """
    def wrapped(*args, **kwargs):
        if USE_OTEL_SDK:
            with tracer.start_as_current_span(
                "{} {}".format(method, route),
                kind=SpanKind.SERVER,
            ) as span:
                try:
                    result = handler_fn(*args, **kwargs)
                    if isinstance(result, dict) and "status_code" in result:
                        span.set_attribute("http.status_code", result["status_code"])
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(trace.StatusCode.ERROR, str(e))
                    raise
        else:
            # Sidecar approach
            _sidecar_post({
                "action": "start_span",
                "name": "{} {}".format(method, route),
            })
            try:
                return handler_fn(*args, **kwargs)
            except Exception as e:
                _sidecar_post({
                    "action": "event",
                    "name": "handler.error",
                    "attributes": {"error": str(e), "route": route},
                })
                raise

    return wrapped


# ── Simulated legacy entry points ─────────────────────────────────────────────
def _process_order_handler(order_id, amount, customer_tier):
    """Original business logic — NOT modified."""
    fraud_score = random.uniform(0.0, 1.0)
    if fraud_score > 0.85:
        return {"status": "blocked", "fraud_score": fraud_score, "status_code": 402}

    if USE_OTEL_SDK:
        span = trace.get_current_span()
        span.set_attribute("order.id",          order_id)
        span.set_attribute("order.value_usd",   amount)
        span.set_attribute("customer.tier",     customer_tier)
        span.set_attribute("fraud.score",       round(fraud_score, 3))
        span.set_attribute("fraud.decision",    "approved")

    return {"status": "confirmed", "order_id": order_id, "status_code": 200}


# Wrap the handler — Tier B pattern
process_order = instrument_handler(_process_order_handler, "/api/orders", "POST")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Python 2.7 Tier B demo — sending test spans...")

    orders = [
        ("ORD-001", 4200.00, "enterprise"),
        ("ORD-002", 29.99,   "free"),
        ("ORD-003", 1250.00, "pro"),
    ]

    for oid, amount, tier in orders:
        result = process_order(oid, amount, tier)
        print("  {} ${} [{}] → {}".format(oid, amount, tier, result["status"]))

    print("Done. Check Kibana APM → python27-tier-b")
